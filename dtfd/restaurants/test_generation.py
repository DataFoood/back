import json
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from users.models import User
from .generation import generate_answer
from .models import Restaurant
from .views import SearchView


def model_response(content="A Cantina tem opções vegetarianas.", **extra):
    return httpx.Response(
        200,
        request=httpx.Request("POST", "http://ollama:11434/api/chat"),
        json={"done": True, "done_reason": "stop", "message": {"content": content}, **extra},
    )


@override_settings(CHAT_GENERATION_ENABLED=True, CHAT_MODEL="qwen3:0.6b")
class GenerationTest(SimpleTestCase):
    def setUp(self):
        self.results = [{"restaurant": {
            "id": 1, "name": "Cantina", "description": "Opções vegetarianas",
            "cuisines": [{"name": "Italiana"}], "ambients": [], "price_ranges": [],
            "email": "private@example.test", "owner": {"cpf": "private-document"},
        }, "score": 0, "match": None}]

    @override_settings(CHAT_GENERATION_ENABLED=False)
    @patch("restaurants.generation.httpx.post")
    def test_disabled_does_not_call_model(self, remote):
        self.assertIsNone(generate_answer("almoço", self.results))
        remote.assert_not_called()

    @patch("restaurants.generation.httpx.post")
    def test_no_candidates_does_not_invent_recommendations(self, remote):
        self.assertIsNone(generate_answer("almoço", []))
        remote.assert_not_called()

    @patch("restaurants.generation.httpx.post")
    def test_generates_from_bounded_public_context_only(self, remote):
        remote.return_value = model_response()
        self.assertEqual("A Cantina tem opções vegetarianas.", generate_answer("sem carne", self.results * 10))
        payload = remote.call_args.kwargs["json"]
        context = json.loads(payload["messages"][1]["content"])
        self.assertEqual("sem carne", context["query"])
        self.assertEqual(3, len(context["restaurants"]))
        self.assertEqual(["Italiana"], context["restaurants"][0]["cuisines"])
        self.assertNotIn("private", json.dumps(payload))
        self.assertEqual(1024, payload["options"]["num_ctx"])
        self.assertEqual(120, payload["options"]["num_predict"])
        self.assertEqual(1, payload["options"]["num_thread"])
        self.assertFalse(payload["think"])
        self.assertFalse(payload["stream"])
        self.assertEqual("2m", payload["keep_alive"])

    @patch("restaurants.generation.httpx.post", side_effect=httpx.ReadTimeout("offline"))
    def test_timeout_leaves_cards_available(self, remote):
        self.assertIsNone(generate_answer("sem carne", self.results))
        self.assertEqual("Cantina", self.results[0]["restaurant"]["name"])

    @patch("restaurants.generation.httpx.post")
    def test_invalid_or_truncated_output_is_not_displayed_as_complete(self, remote):
        responses = [
            model_response(""), model_response("   "), model_response(None),
            model_response(["texto"]), model_response("a" * 1201),
            model_response(done=False), model_response(done_reason="length"),
            httpx.Response(200, json=[]), httpx.Response(200, json={"done": True, "message": []}),
            httpx.Response(200, text="not json"),
            httpx.Response(503, request=httpx.Request("POST", "http://ollama:11434/api/chat")),
        ]
        for response in responses:
            with self.subTest(response=response):
                response.request = httpx.Request("POST", "http://ollama:11434/api/chat")
                remote.return_value = response
                self.assertIsNone(generate_answer("sem carne", self.results))


@override_settings(
    CHAT_GENERATION_ENABLED=True, CHAT_MODEL="qwen3:0.6b",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class SearchGenerationTest(SimpleTestCase):
    def request(self, data, authenticated=True):
        request = APIRequestFactory().post("/api/search/", data, format="json")
        if authenticated:
            force_authenticate(request, user=User(pk=1, allow_info=False))
        return SearchView.as_view()(request)

    @patch("restaurants.generation.httpx.post")
    def test_authentication_and_query_validation_precede_inference(self, remote):
        self.assertEqual(401, self.request({"query": "pizza"}, authenticated=False).status_code)
        self.assertEqual(400, self.request({"query": ["pizza"]}).status_code)
        remote.assert_not_called()

    @override_settings(SEMANTIC_SEARCH_ENABLED=False)
    @patch("restaurants.generation.httpx.post")
    @patch("restaurants.views.public_catalog")
    def test_empty_text_results_keep_response_without_model_call(self, catalog, remote):
        catalog.return_value = Restaurant.objects.none()
        response = self.request({"query": "pizza"})
        self.assertEqual(200, response.status_code)
        self.assertEqual([], response.data["results"])
        self.assertEqual("text", response.data["mode"])
        self.assertIsNone(response.data["answer"])
        remote.assert_not_called()

    @override_settings(SEMANTIC_SEARCH_ENABLED=True)
    @patch("restaurants.views.httpx.post")
    @patch.object(SearchView, "_hydrate")
    @patch("restaurants.views.public_catalog")
    def test_returns_explanation_with_retrieved_cards(self, catalog, hydrate, remote):
        catalog.return_value = Restaurant.objects.none()
        hydrate.return_value = [{"restaurant": {
            "name": "Cantina", "description": "", "cuisines": [], "ambients": [], "price_ranges": [],
        }, "score": 1, "match": 80}]
        remote.side_effect = [httpx.Response(200, json={"results": []}), model_response()]
        response = self.request({"query": "almoço"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("A Cantina tem opções vegetarianas.", response.data["answer"])
        self.assertEqual("Cantina", response.data["results"][0]["restaurant"]["name"])

    @override_settings(SEMANTIC_SEARCH_ENABLED=True)
    @patch("restaurants.views.httpx.post")
    @patch.object(SearchView, "_hydrate")
    @patch("restaurants.views.public_catalog")
    def test_model_failure_preserves_retrieved_cards(self, catalog, hydrate, remote):
        catalog.return_value = Restaurant.objects.none()
        hydrate.return_value = [{"restaurant": {
            "name": "Cantina", "description": "", "cuisines": [], "ambients": [], "price_ranges": [],
        }, "score": 1, "match": 80}]
        remote.side_effect = [
            httpx.Response(200, json={"results": []}), httpx.ReadTimeout("offline"),
        ]
        response = self.request({"query": "almoço"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("Cantina", response.data["results"][0]["restaurant"]["name"])
        self.assertEqual("semantic", response.data["mode"])
        self.assertIsNone(response.data["answer"])
