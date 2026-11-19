import json
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.core.cache import cache
from rest_framework.test import APITestCase

from address.models import Address
from django.contrib.contenttypes.models import ContentType
from preferences.models import UserCuisineAffinity
from restaurants.models import Ambient, Cuisine, Restaurant, RestaurantFavorite
from users.models import User
from .models import ChatConversation
from .recommendations import interpret_turn, personal_context


@override_settings(CHAT_GENERATION_ENABLED=True)
class InterpretationTest(SimpleTestCase):
    @patch("restaurants.generation.httpx.post")
    def test_explicit_filters_are_applied_without_calling_the_model(self, remote):
        choices = {"city": [{"name": "Marília"}], "ambient": [{"id": 2, "name": "Ao Ar Livre"}]}
        turn = interpret_turn("jantar em Marilia em um lugar aberto", {}, choices)
        self.assertEqual("Marília", turn.filters.city)
        self.assertEqual(2, turn.filters.ambient)
        self.assertTrue(turn.ready)
        quoted = interpret_turn('Quero jantar em "Marília"', {}, choices)
        self.assertEqual("Marília", quoted.filters.city)
        self.assertIsNone(quoted.filters.text)
        remote.assert_not_called()

    def test_removal_is_distinct_from_exclusion_and_open_now(self):
        choices = {"ambient": [{"id": 2, "name": "Ao Ar Livre"}]}
        previous = {"city": "Marília", "ambient": 2}
        turn = interpret_turn("não precisa ser ao ar livre", previous, choices)
        self.assertEqual(["ambient"], turn.remove_filters)
        self.assertEqual({}, turn.filters.model_dump(exclude_none=True))
        self.assertIsNone(interpret_turn("não quero ao ar livre", previous, choices))
        self.assertFalse(interpret_turn("um lugar aberto agora", {}, choices).ready)
        self.assertEqual(2, interpret_turn("ao ar livre e aberto agora", {}, choices).filters.ambient)
        self.assertFalse(interpret_turn("oi, tudo bem?", {}, choices).ready)

    def test_ambiguous_filters_do_not_choose_arbitrarily(self):
        choices = {"city": [{"name": "Marília"}, {"name": "Campinas"}]}
        self.assertIsNone(interpret_turn("Marília ou Campinas", {}, choices))

    def test_explicit_reset_and_delivery_optional(self):
        reset = interpret_turn("sem filtros", {"city": "Marília", "ambient": 2}, {})
        self.assertTrue(reset.ready)
        self.assertEqual({"city", "ambient"}, set(reset.remove_filters))
        self.assertFalse(interpret_turn("não preciso de delivery", {}, {}).filters.delivery)
        self.assertFalse(interpret_turn("não precisa ter delivery", {}, {}).filters.delivery)

    def test_catalog_restaurant_name_uses_the_model_name_limit(self):
        name = "Restaurante " + "a" * 188
        turn = interpret_turn(name, {}, {"text": [{"name": name}]})
        self.assertTrue(turn.ready)
        self.assertEqual(name, turn.filters.text)


@override_settings(CHAT_GENERATION_ENABLED=True, SHOW_DEMO_RESTAURANTS=True,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class AssistantFlowTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="chat@test.example", name="Pessoa", password="Testing12345")
        cls.other = User.objects.create_user(email="other@test.example", name="Outra", password="Testing12345")
        cls.outdoor = Ambient.objects.get(name="Ao Ar Livre")
        cls.italian = Cuisine.objects.get(name="Italiana")
        ct = ContentType.objects.get_for_model(Restaurant)
        for i in range(12):
            restaurant = Restaurant.objects.create(name=f"Restaurante {i:02}", slug=f"chat-{i}")
            Address.objects.create(content_type=ct, object_id=restaurant.pk, city="Marília", state="SP")
            if i < 4:
                restaurant.ambients.add(cls.outdoor)
        cls.favorite = Restaurant.objects.get(slug="chat-11")
        cls.favorite.cuisines.add(cls.italian)
        UserCuisineAffinity.objects.create(user=cls.user, cuisine=cls.italian, score=1)
        RestaurantFavorite.objects.create(user=cls.user, restaurant=cls.favorite)

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.user)
        writer = patch("restaurants.generation.httpx.post", return_value=httpx.Response(
            200, request=httpx.Request("POST", "http://ollama/api/chat"),
            json={"done": True, "done_reason": "stop", "message": {"content": "Você pode ver as opções ou continuar conversando."}},
        ))
        self.remote = writer.start()
        self.addCleanup(writer.stop)

    @staticmethod
    def turn(reply, ready=True, **filters):
        from .recommendations import AssistantTurn
        return AssistantTurn(reply=reply, ready=ready, filters=filters)

    @patch("chats.assistant_views.interpret_turn")
    def test_refines_twelve_to_four_and_stores_small_snapshots(self, interpret):
        interpret.side_effect = [self.turn("Encontrei opções para jantar.", city="Marília"),
                                 self.turn("Vamos considerar lugares ao ar livre.", city=None, ambient=self.outdoor.pk)]
        first = self.client.post("/api/chats/respond/", {"query": "jantar em Marília"}, format="json")
        self.assertEqual(200, first.status_code, first.data)
        conversation = first.json()
        content = conversation["messages"][-1]["content"]
        self.assertEqual(12, content["count"])
        self.assertEqual([], content["results"])
        self.assertEqual(12, len(content["recommendation_ids"]))
        second = self.client.post("/api/chats/respond/", {"query": "e que seja em um lugar aberto", "conversation_id": conversation["id"]}, format="json")
        self.assertEqual(200, second.status_code, second.data)
        content = second.json()["messages"][-1]["content"]
        self.assertEqual(4, content["count"])
        self.assertEqual("Marília", content["filters"]["city"])
        self.assertEqual(4, len(second.json()["messages"]))
        selected = self.client.get(f"/api/chats/{conversation['id']}/recommendations/3/")
        self.assertEqual(200, selected.status_code)
        self.assertEqual(4, selected.json()["count"])
        self.assertTrue(all(any(tag["id"] == self.outdoor.pk for tag in card["ambients"]) for card in selected.json()["results"]))

    @patch("restaurants.generation.httpx.post")
    def test_observed_empty_model_filters_cannot_ignore_city_or_outdoor_request(self, remote):
        remote.return_value = httpx.Response(200, request=httpx.Request("POST", "http://ollama/api/chat"), json={
            "done": True, "done_reason": "stop", "message": {"content": json.dumps({
                "reply": "Não há informações sobre restaurantes em Marília com filtros adicionais.",
                "ready": True, "filters": {}, "remove_filters": [],
            })},
        })
        first = self.client.post("/api/chats/respond/", {"query": "Quero jantar em Marília"}, format="json")
        self.assertEqual(200, first.status_code)
        content = first.json()["messages"][-1]["content"]
        self.assertEqual("Marília", content["filters"].get("city"))
        self.assertEqual(12, content["count"])
        second = self.client.post("/api/chats/respond/", {
            "query": "E que seja em um lugar aberto", "conversation_id": first.json()["id"],
        }, format="json")
        content = second.json()["messages"][-1]["content"]
        self.assertEqual("Marília", content["filters"]["city"])
        self.assertEqual(self.outdoor.pk, content["filters"]["ambient"])
        self.assertEqual(4, content["count"])
        self.assertNotIn("Não há informações", content["answer"])

    @patch("restaurants.generation.httpx.post")
    def test_unrecognized_request_does_not_silently_select_entire_catalog(self, remote):
        remote.return_value = httpx.Response(200, request=httpx.Request("POST", "http://ollama/api/chat"), json={
            "done": True, "done_reason": "stop", "message": {"content": json.dumps({
                "reply": "Vamos buscar", "ready": True, "filters": {},
            })},
        })
        response = self.client.post("/api/chats/respond/", {"query": "Oi, tudo bem?"}, format="json")
        self.assertEqual(0, response.json()["messages"][-1]["content"]["count"])

    def test_real_marilia_catalog_does_not_invent_outdoor_data_and_can_refine_to_pizza(self):
        from pathlib import Path
        from django.core.management import call_command
        from io import StringIO
        call_command("import_osm", file=Path(__file__).resolve().parents[2] / "data/marilia-osm-20261119.json",
                     replace=True, stdout=StringIO())
        first = self.client.post("/api/chats/respond/", {"query": "Quero jantar em Marília"}, format="json").json()
        self.assertEqual(41, first["messages"][-1]["content"]["count"])
        second = self.client.post("/api/chats/respond/", {
            "query": "E que seja em um lugar aberto", "conversation_id": first["id"],
        }, format="json").json()
        # O único objeto OSM ao ar livre não tem nome e não entra no catálogo.
        self.assertEqual(0, second["messages"][-1]["content"]["count"])
        self.assertIn("Não encontrei", second["messages"][-1]["content"]["answer"])
        self.assertEqual(1, self.remote.call_count)
        third = self.client.post("/api/chats/respond/", {
            "query": "Não precisa ser ao ar livre, quero pizza", "conversation_id": first["id"],
        }, format="json").json()
        self.assertEqual(5, third["messages"][-1]["content"]["count"])
        payload = self.remote.call_args.kwargs["json"]
        context = json.loads(payload["messages"][1]["content"])
        self.assertEqual({"city": "Marília", "cuisine": "Pizza & Massas"}, context["filtros"])
        self.assertEqual(2, len(context["restaurantes"]))
        self.assertTrue(all("Pizza & Massas" in row["cuisines"] for row in context["restaurantes"]))
        self.assertEqual(2, self.remote.call_count)

    def test_probe_measures_real_flow_without_persisting_conversations_or_accounts(self):
        from pathlib import Path
        from django.core.management import call_command
        from io import StringIO
        call_command("import_osm", file=Path(__file__).resolve().parents[2] / "data/marilia-osm-20261119.json",
                     replace=True, stdout=StringIO())
        output = StringIO()
        call_command("probe_chat", stdout=output)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([41, 5, 0], [row["recommendations"] for row in rows])
        self.assertEqual(2, self.remote.call_count)
        self.assertFalse(ChatConversation.objects.exists())
        self.assertEqual(2, User.objects.count())

    @patch("chats.assistant_views.interpret_turn")
    def test_other_accounts_cannot_read_context_or_selection(self, interpret):
        chat = ChatConversation.objects.create(user=self.other, title="Outra conversa", messages=[])
        self.assertEqual(404, self.client.post("/api/chats/respond/", {"query": "oi", "conversation_id": chat.pk}, format="json").status_code)
        self.assertEqual(404, self.client.get(f"/api/chats/{chat.pk}/recommendations/1/").status_code)
        interpret.assert_not_called()

    def test_only_premium_with_consent_uses_own_profile(self):
        self.assertEqual({}, personal_context(self.user))
        self.user.level = 2
        self.assertEqual({}, personal_context(self.user))
        self.user.allow_info = True
        profile = personal_context(self.user)
        self.assertEqual("Italiana", profile["cuisine"][0]["name"])
        self.assertEqual(self.favorite.pk, profile["favorites"][0]["id"])
        self.assertNotIn("email", json.dumps(profile))
        self.assertEqual({}, personal_context(self.other))
        self.other.level, self.other.allow_info = 2, True
        self.assertEqual({}, personal_context(self.other))

    @patch("chats.assistant_views.interpret_turn")
    def test_client_cannot_choose_premium_and_premium_does_not_override_filters(self, interpret):
        interpret.return_value = self.turn("Quais opções você prefere?", city="Marília")
        response = self.client.post("/api/chats/respond/", {"query": "jantar", "level": 2, "plan": "premium"}, format="json")
        self.assertEqual("free", response.json()["messages"][-1]["content"]["plan"])
        context = json.loads(self.remote.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertNotIn("preferencias", context)
        self.assertNotIn("favoritos", context)
        self.user.level, self.user.allow_info = 2, True
        self.user.save(update_fields=["level", "allow_info"])
        response = self.client.post("/api/chats/respond/", {"query": "jantar"}, format="json")
        content = response.json()["messages"][-1]["content"]
        self.assertEqual("premium", content["plan"])
        self.assertTrue(content["personalized"])
        self.assertEqual(12, content["count"])
        self.assertEqual(self.favorite.pk, content["recommendation_ids"][0])
        payload = self.remote.call_args.kwargs["json"]
        context = json.loads(payload["messages"][1]["content"])
        self.assertEqual(["Italiana"], context["preferencias"])
        self.assertEqual([self.favorite.name], context["favoritos"])
        self.assertNotIn("email", json.dumps(context))
        self.assertNotIn("format", payload)
        self.assertEqual(1024, payload["options"]["num_ctx"])
        self.assertEqual(120, payload["options"]["num_predict"])

    def test_model_timeout_preserves_the_real_filtered_selection(self):
        self.remote.side_effect = httpx.ReadTimeout("offline")
        response = self.client.post("/api/chats/respond/", {"query": "Marília ao ar livre"}, format="json")
        content = response.json()["messages"][-1]["content"]
        self.assertEqual(4, content["count"])
        self.assertIn("Não consegui escrever", content["answer"])
        self.assertEqual(1, self.remote.call_count)

    @patch("chats.assistant_views.interpret_turn")
    def test_failure_retains_selection_without_claiming_refinement(self, interpret):
        interpret.side_effect = [self.turn("Vamos buscar.", city="Marília"), None]
        first = self.client.post("/api/chats/respond/", {"query": "jantar"}, format="json").json()
        response = self.client.post("/api/chats/respond/", {"query": "ao ar livre", "conversation_id": first["id"]}, format="json")
        content = response.json()["messages"][-1]["content"]
        self.assertEqual(12, content["count"])
        self.assertIn("Não consegui", content["answer"])

    @patch("chats.assistant_views.interpret_turn")
    def test_greeting_and_empty_catalog_do_not_invent_results(self, interpret):
        interpret.return_value = self.turn("Em qual cidade você quer comer?", ready=False)
        response = self.client.post("/api/chats/respond/", {"query": "oi"}, format="json")
        self.assertEqual(0, response.json()["messages"][-1]["content"]["count"])
        interpret.return_value = self.turn("Vou procurar.", city="Cidade sem dados")
        response = self.client.post("/api/chats/respond/", {"query": "jantar"}, format="json")
        content = response.json()["messages"][-1]["content"]
        self.assertEqual(0, content["count"])
        self.assertIn("Não encontrei", content["answer"])

    @patch("chats.assistant_views.interpret_turn")
    def test_input_validation_and_auth_precede_inference(self, interpret):
        for payload in ({"query": " "}, {"query": "x" * 501}, {"query": "oi", "conversation_id": -1}):
            self.assertEqual(400, self.client.post("/api/chats/respond/", payload, format="json").status_code)
        self.client.force_authenticate(None)
        self.assertEqual(401, self.client.post("/api/chats/respond/", {"query": "oi"}, format="json").status_code)
        interpret.assert_not_called()

    @patch("chats.assistant_views.interpret_turn")
    def test_consented_queries_become_context_for_future_premium_chats(self, interpret):
        from preferences.models import SearchHistory
        interpret.return_value = self.turn("Vamos buscar.", city="Marília")
        self.client.post("/api/chats/respond/", {"query": "jantar italiano"}, format="json")
        self.assertFalse(SearchHistory.objects.filter(user=self.user).exists())
        self.user.level, self.user.allow_info = 2, True
        self.user.save(update_fields=["level", "allow_info"])
        self.client.post("/api/chats/respond/", {"query": "almoço vegetariano"}, format="json")
        self.assertEqual(["almoço vegetariano"], personal_context(self.user)["recent_searches"])

    @patch("chats.assistant_views.interpret_turn")
    def test_concurrent_update_requires_reopening_instead_of_applying_stale_filters(self, interpret):
        chat = ChatConversation.objects.create(user=self.user, title="Busca", messages=[])
        def update_during_inference(*args):
            chat.title = "Atualizado em outra aba"
            chat.save()
            return self.turn("Vamos buscar.", city="Marília")
        interpret.side_effect = update_during_inference
        response = self.client.post("/api/chats/respond/", {"query": "jantar", "conversation_id": chat.pk}, format="json")
        self.assertEqual(409, response.status_code)
        chat.refresh_from_db()
        self.assertEqual([], chat.messages)

    @patch("chats.assistant_views.interpret_turn")
    def test_selection_cap_is_explicit_and_removed_records_are_not_exposed(self, interpret):
        Restaurant.objects.bulk_create([Restaurant(name=f"Extra {i}", slug=f"extra-{i}") for i in range(55)])
        interpret.return_value = self.turn("Vamos buscar.")
        response = self.client.post("/api/chats/respond/", {"query": "recomende lugares"}, format="json")
        content = response.json()["messages"][-1]["content"]
        self.assertEqual(50, content["count"])
        self.assertTrue(content["limited"])
        Restaurant.objects.filter(pk=content["recommendation_ids"][0]).update(is_demo=True)
        with override_settings(SHOW_DEMO_RESTAURANTS=False):
            selection = self.client.get(f"/api/chats/{response.json()['id']}/recommendations/1/").json()
        self.assertEqual(49, selection["count"])
        self.assertFalse(any(card["is_demo"] for card in selection["results"]))

    @patch("chats.assistant_views.interpret_turn")
    def test_explicit_removal_relaxes_only_the_requested_filter(self, interpret):
        from .recommendations import AssistantTurn
        interpret.return_value = self.turn("Vamos buscar.", city="Marília", ambient=self.outdoor.pk)
        first = self.client.post("/api/chats/respond/", {"query": "ao ar livre em Marília"}, format="json").json()
        self.assertEqual(4, first["messages"][-1]["content"]["count"])
        interpret.return_value = AssistantTurn(reply="Pode ser qualquer ambiente.", ready=True, filters={}, remove_filters=["ambient"])
        response = self.client.post("/api/chats/respond/", {"query": "não precisa ser ao ar livre", "conversation_id": first["id"]}, format="json")
        content = response.json()["messages"][-1]["content"]
        self.assertEqual(12, content["count"])
        self.assertEqual("Marília", content["filters"]["city"])
        self.assertNotIn("ambient", content["filters"])

    @patch("chats.assistant_views.interpret_turn")
    def test_delivery_not_required_keeps_restaurants_that_also_deliver(self, interpret):
        self.favorite.has_delivery = True
        self.favorite.save(update_fields=["has_delivery"])
        interpret.return_value = self.turn("Com delivery.", city="Marília", delivery=True)
        first = self.client.post("/api/chats/respond/", {"query": "quero delivery"}, format="json").json()
        self.assertEqual(1, first["messages"][-1]["content"]["count"])
        interpret.return_value = self.turn("Delivery não é obrigatório.", delivery=False)
        response = self.client.post("/api/chats/respond/", {"query": "não precisa ter delivery", "conversation_id": first["id"]}, format="json")
        self.assertEqual(12, response.json()["messages"][-1]["content"]["count"])
