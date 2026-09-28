"""Regressões de segurança/robustez encontradas na rodada de testes finais.

Cada teste reproduz um problema real observado contra a API rodando (ver
final-tests/README.md -> "Achados") e trava a correção.

Rodar (a partir de dtfd/, com Postgres + Redis de pé):
    uv run python manage.py test ../final-tests
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from restaurants.models import BusinessHour, Restaurant
from users.models import User

PASSWORD = "SenhaForte123"


def make_user(email, name="Pessoa Teste", **extra):
    return User.objects.create_user(email=email, password=PASSWORD, name=name, **extra)


def login(client, email, password=PASSWORD):
    response = client.post("/api/users/login/", {"email": email, "password": password}, format="json")
    assert response.status_code == 200, response.content
    return response.json()


class SessionRevocationTest(APITestCase):
    """Trocar a senha / encerrar a conta precisa derrubar as sessões abertas."""

    def setUp(self):
        cache.clear()
        self.user = make_user("sessao@dtfd.com")

    def test_password_change_revokes_old_refresh_tokens(self):
        other_device = login(self.client, "sessao@dtfd.com")
        this_device = login(self.client, "sessao@dtfd.com")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {this_device['access']}")
        response = self.client.post(
            f"/api/users/{self.user.pk}/change-password/",
            {"current_password": PASSWORD, "new_password": "NovaSenha@456", "confirm_password": "NovaSenha@456"},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        body = response.json()
        self.assertIn("access", body, "devolve par novo para a sessão atual continuar")
        self.assertIn("refresh", body)

        self.client.credentials()
        for old in (other_device["refresh"], this_device["refresh"]):
            refreshed = self.client.post("/api/users/login/refresh/", {"refresh": old}, format="json")
            self.assertEqual(status.HTTP_401_UNAUTHORIZED, refreshed.status_code,
                             "refresh emitido antes da troca de senha não pode mais renovar")
        fresh = self.client.post("/api/users/login/refresh/", {"refresh": body["refresh"]}, format="json")
        self.assertEqual(status.HTTP_200_OK, fresh.status_code)

    def test_deleted_account_refresh_is_401_not_500(self):
        tokens = login(self.client, "sessao@dtfd.com")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(204, self.client.delete(f"/api/users/{self.user.pk}/delete/").status_code)
        self.client.credentials()
        response = self.client.post("/api/users/login/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_soft_deleted_user_with_unrevoked_token_gets_401(self):
        # conta removida por fora da API (admin/shell): o token não foi
        # blacklistado, mas o refresh não pode estourar DoesNotExist
        tokens = login(self.client, "sessao@dtfd.com")
        User.all_objects.filter(pk=self.user.pk).update(deleted_at="2026-01-01T00:00:00Z")
        response = self.client.post("/api/users/login/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)


class LoginThrottleSpoofingTest(APITestCase):
    """O limite de login não pode ser burlado trocando o X-Forwarded-For."""

    def setUp(self):
        cache.clear()
        make_user("alvo@dtfd.com")

    def test_rotating_forwarded_for_does_not_reset_the_limit(self):
        data = {"email": "alvo@dtfd.com", "password": "errada"}
        codes = [
            self.client.post("/api/users/login/", data, format="json",
                             HTTP_X_FORWARDED_FOR=f"203.0.113.{i}").status_code
            for i in range(7)
        ]
        self.assertIn(status.HTTP_429_TOO_MANY_REQUESTS, codes, codes)

    @override_settings(REST_FRAMEWORK={
        "NUM_PROXIES": 1,
        "DEFAULT_THROTTLE_RATES": {"login": "5/min", "register": "10/hour", "search": "30/min"},
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    })
    def test_behind_proxy_uses_last_hop_as_client_ip(self):
        # atrás do Caddy o IP real é o último item do XFF; prefixos forjados
        # pelo cliente não mudam a identidade
        data = {"email": "alvo@dtfd.com", "password": "errada"}
        codes = [
            self.client.post("/api/users/login/", data, format="json",
                             HTTP_X_FORWARDED_FOR=f"10.9.9.{i}, 198.51.100.7").status_code
            for i in range(7)
        ]
        self.assertIn(status.HTTP_429_TOO_MANY_REQUESTS, codes, codes)


class SearchInputValidationTest(APITestCase):
    """Payload inválido na busca é erro do cliente (400), nunca 500/503."""

    def setUp(self):
        cache.clear()
        self.user = make_user("busca@dtfd.com")
        self.client.force_authenticate(self.user)

    def test_non_string_query(self):
        response = self.client.post("/api/search/", {"query": ["pizza"]}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_query_too_long(self):
        response = self.client.post("/api/search/", {"query": "a" * 501}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_invalid_limits(self):
        for limit in ("abc", 0, 51, True, 2.5):
            with self.subTest(limit=limit):
                response = self.client.post("/api/search/", {"query": "pizza", "limit": limit}, format="json")
                self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    @patch("restaurants.views.httpx.post")
    def test_valid_limit_is_forwarded(self, mock_post):
        fake = MagicMock(status_code=200)
        fake.json.return_value = {"results": []}
        mock_post.return_value = fake
        response = self.client.post("/api/search/", {"query": "pizza", "limit": 6}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(6, mock_post.call_args.kwargs["json"]["limit"])


class OwnerViewCountTest(APITestCase):
    """O painel do dono recarrega o detalhe a cada edição: isso não pode
    inflar a métrica de visualizações que ele mesmo acompanha."""

    def setUp(self):
        self.owner = make_user("dono@dtfd.com")
        self.visitor = make_user("visita@dtfd.com")
        self.restaurant = Restaurant.objects.create(owner=self.owner, name="Cantina", slug="cantina")
        self.url = f"/api/restaurants/{self.restaurant.pk}/"

    def test_owner_views_do_not_count(self):
        self.client.force_authenticate(self.owner)
        self.client.get(self.url)
        self.client.get(f"/api/restaurants/by-slug/{self.restaurant.slug}/")
        self.restaurant.refresh_from_db()
        self.assertEqual(0, self.restaurant.view_count)

    def test_visitors_and_anonymous_count(self):
        self.client.get(self.url)
        self.client.force_authenticate(self.visitor)
        self.client.get(self.url)
        self.restaurant.refresh_from_db()
        self.assertEqual(2, self.restaurant.view_count)


class BusinessHourRecreateTest(APITestCase):
    """Recriar o horário de um dia removido (soft delete) dava IntegrityError
    (500) por causa da UniqueConstraint (restaurant, day_week)."""

    def setUp(self):
        self.owner = make_user("horas@dtfd.com")
        self.restaurant = Restaurant.objects.create(owner=self.owner, name="Bar", slug="bar")
        self.base = f"/api/restaurants/{self.restaurant.pk}/hours/"
        self.client.force_authenticate(self.owner)

    def test_recreate_after_soft_delete(self):
        created = self.client.post(self.base, {"day_week": 2, "is_closed": True, "meta_interval": {}}, format="json")
        self.assertEqual(201, created.status_code)
        self.assertEqual(204, self.client.delete(f"{self.base}{created.json()['id']}/").status_code)

        again = self.client.post(
            self.base,
            {"day_week": 2, "is_closed": False, "meta_interval": {"almoco": ["11:00:00", "15:00:00"]}},
            format="json",
        )
        self.assertEqual(status.HTTP_201_CREATED, again.status_code, again.content)
        self.assertEqual(1, BusinessHour.objects.filter(restaurant=self.restaurant, day_week=2).count())
        self.assertFalse(again.json()["is_closed"])

    def test_duplicate_active_day_still_rejected(self):
        self.client.post(self.base, {"day_week": 3, "is_closed": True, "meta_interval": {}}, format="json")
        dup = self.client.post(self.base, {"day_week": 3, "is_closed": True, "meta_interval": {}}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, dup.status_code)


class RecomputeInputTest(APITestCase):
    def test_invalid_user_id_is_400(self):
        admin = User.objects.create_superuser(email="adm@dtfd.com", password=PASSWORD, name="Adm")
        self.client.force_authenticate(admin)
        response = self.client.post("/api/preferences/recompute/", {"user_id": "abc"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)


class AccessControlMatrixTest(APITestCase):
    """Varredura de autorização: um usuário comum tentando mexer no que é
    de outro dono em todas as rotas de escrita."""

    def setUp(self):
        self.owner = make_user("dono2@dtfd.com")
        self.intruder = make_user("intruso@dtfd.com")
        self.restaurant = Restaurant.objects.create(owner=self.owner, name="Alvo", slug="alvo")
        rid = self.restaurant.pk
        self.client.force_authenticate(self.owner)
        self.item = self.client.post(f"/api/restaurants/{rid}/items/", {"name": "Prato"}, format="json").json()
        self.image = self.client.post(f"/api/restaurants/{rid}/images/", {"url": "https://example.com/a.jpg"}, format="json").json()
        self.hour = self.client.post(f"/api/restaurants/{rid}/hours/", {"day_week": 0, "is_closed": True, "meta_interval": {}}, format="json").json()
        self.client.force_authenticate(self.intruder)

    def test_intruder_cannot_write(self):
        rid = self.restaurant.pk
        attempts = [
            ("patch", f"/api/restaurants/{rid}/", {"name": "hack"}),
            ("delete", f"/api/restaurants/{rid}/", None),
            ("get", f"/api/restaurants/{rid}/stats/", None),
            ("post", f"/api/restaurants/{rid}/items/", {"name": "x"}),
            ("patch", f"/api/restaurants/{rid}/items/{self.item['id']}/", {"name": "x"}),
            ("delete", f"/api/restaurants/{rid}/items/{self.item['id']}/", None),
            ("post", f"/api/restaurants/{rid}/images/", {"url": "https://evil.test/x.png"}),
            ("delete", f"/api/restaurants/{rid}/images/{self.image['id']}/", None),
            ("post", f"/api/restaurants/{rid}/hours/", {"day_week": 1, "is_closed": True, "meta_interval": {}}),
            ("patch", f"/api/restaurants/{rid}/hours/{self.hour['id']}/", {"is_closed": False}),
            ("post", "/api/addresses/", {"entity_type": "restaurant", "object_id": rid, "street": "R",
                                        "city": "C", "state": "SP", "zipcode": "1"}),
            ("patch", f"/api/users/{self.owner.pk}/", {"name": "hack"}),
            ("post", f"/api/users/{self.owner.pk}/change-password/", {"current_password": "x", "new_password": "y", "confirm_password": "y"}),
            ("delete", f"/api/users/{self.owner.pk}/delete/", None),
        ]
        for method, url, body in attempts:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, body, format="json") if body is not None else getattr(self.client, method)(url)
                self.assertIn(response.status_code, (403, 404), f"{method.upper()} {url} -> {response.status_code}")
        self.restaurant.refresh_from_db()
        self.assertEqual("Alvo", self.restaurant.name)
        self.assertIsNone(self.restaurant.deleted_at)

    def test_javascript_urls_rejected(self):
        # cover_image/website/menu_url/fotos são renderizados como href/src no front
        self.client.force_authenticate(self.owner)
        rid = self.restaurant.pk
        for field in ("website", "cover_image", "menu_url"):
            with self.subTest(field=field):
                response = self.client.patch(f"/api/restaurants/{rid}/", {field: "javascript:alert(1)"}, format="json")
                self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        response = self.client.post(f"/api/restaurants/{rid}/images/", {"url": "javascript:alert(1)"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
