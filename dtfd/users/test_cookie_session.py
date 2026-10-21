from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from chats.models import ChatConversation

from .models import User

BROWSER = {"X-Requested-With": "datafood"}
ACCESS = settings.AUTH_COOKIE_ACCESS
REFRESH = settings.AUTH_COOKIE_REFRESH


class CookieSessionTest(APITestCase):
    """Sessão do navegador: tokens só em cookie HttpOnly, nunca no corpo."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="c@dtfd.com", password="SenhaForte123", name="Cliente")

    def login(self):
        return self.client.post(
            "/api/users/login/", {"email": "c@dtfd.com", "password": "SenhaForte123"}, format="json", headers=BROWSER
        )

    def test_login_sets_httponly_cookies_without_tokens_in_body(self):
        response = self.login()
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        body = response.json()
        self.assertNotIn("access", body)
        self.assertNotIn("refresh", body)
        self.assertEqual("c@dtfd.com", body["user"]["email"])
        self.assertEqual(15 * 60, body["access_expires_in"])
        self.assertTrue(response.cookies[ACCESS]["httponly"])
        self.assertTrue(response.cookies[REFRESH]["httponly"])
        self.assertEqual("/api/users/", response.cookies[REFRESH]["path"], "refresh só vai para as rotas de sessão")
        self.assertEqual("Lax", response.cookies[ACCESS]["samesite"])

    def test_cookie_authenticates(self):
        self.login()
        response = self.client.get("/api/users/me/")
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_write_with_cookie_requires_browser_header(self):
        """CSRF: escrita via cookie sem o cabeçalho (form de outro site) é barrada."""
        self.login()
        response = self.client.patch("/api/users/me/", {"name": "Hacker"}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)
        response = self.client.patch("/api/users/me/", {"name": "Novo"}, format="json", headers=BROWSER)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_refresh_from_cookie_rotates_and_keeps_tokens_out_of_body(self):
        self.login()
        old_refresh = self.client.cookies[REFRESH].value
        response = self.client.post("/api/users/login/refresh/", {}, format="json", headers=BROWSER)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual({"access_expires_in"}, set(response.json()))
        self.assertNotEqual(old_refresh, self.client.cookies[REFRESH].value, "refresh rotaciona")
        # o antigo foi para a blacklist
        self.client.cookies[REFRESH] = old_refresh
        response = self.client.post("/api/users/login/refresh/", {}, format="json", headers=BROWSER)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)
        self.assertEqual("", response.cookies[REFRESH].value, "401 apaga os cookies")

    def test_refresh_without_cookie_is_401(self):
        response = self.client.post("/api/users/login/refresh/", {}, format="json", headers=BROWSER)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_expired_access_cookie_is_anonymous_on_public_routes(self):
        self.client.cookies[ACCESS] = "lixo"
        self.assertEqual(status.HTTP_200_OK, self.client.get("/api/restaurants/").status_code)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, self.client.get("/api/users/me/").status_code)

    def test_logout_blacklists_cookie_refresh_and_clears_cookies(self):
        self.login()
        refresh = self.client.cookies[REFRESH].value
        response = self.client.post("/api/users/logout/", {}, format="json", headers=BROWSER)
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertEqual("", response.cookies[ACCESS].value)
        self.client.cookies[REFRESH] = refresh
        response = self.client.post("/api/users/login/refresh/", {}, format="json", headers=BROWSER)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_register_in_browser_mode(self):
        response = self.client.post(
            "/api/users/register/",
            {"name": "Nova", "email": "n@dtfd.com", "password": "SenhaForte123", "confirm_password": "SenhaForte123"},
            format="json", headers=BROWSER,
        )
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        self.assertNotIn("access", response.json())
        self.assertIn(ACCESS, response.cookies)

    def test_change_password_renews_cookies(self):
        self.login()
        response = self.client.post(
            f"/api/users/{self.user.pk}/change-password/",
            {"current_password": "SenhaForte123", "new_password": "OutraSenha456", "confirm_password": "OutraSenha456"},
            format="json", headers=BROWSER,
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertNotIn("refresh", response.json())
        self.assertEqual(status.HTTP_200_OK, self.client.get("/api/users/me/").status_code, "esta sessão segue")

    def test_delete_account_clears_cookies_and_conversations(self):
        self.login()
        ChatConversation.objects.create(user=self.user, title="pizza", messages=[{"role": "user", "text": "pizza"}])
        response = self.client.delete(f"/api/users/{self.user.pk}/delete/", headers=BROWSER)
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertEqual("", response.cookies[ACCESS].value)
        self.assertFalse(ChatConversation.objects.filter(user=self.user).exists())

    def test_api_clients_keep_bearer_contract(self):
        """Sem o cabeçalho do navegador (Postman, Swagger): tokens no corpo, sem cookie."""
        response = self.client.post(
            "/api/users/login/", {"email": "c@dtfd.com", "password": "SenhaForte123"}, format="json"
        )
        self.assertIn("access", response.json())
        self.assertNotIn(ACCESS, response.cookies)
