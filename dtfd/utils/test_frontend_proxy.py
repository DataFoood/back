from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase
from users.models import User

SECRET = "segredo-de-teste"


@override_settings(FRONTEND_PROXY_SECRET=SECRET)
class FrontendProxyThrottleTest(APITestCase):
    """Via proxy do front, o limite de login é por usuário, não pelo IP da Vercel."""

    def setUp(self):
        cache.clear()
        User.objects.create_user(email="p@dtfd.com", password="SenhaForte123", name="P")

    def wrong_login(self, **headers):
        return self.client.post(
            "/api/users/login/", {"email": "p@dtfd.com", "password": "errada"}, format="json",
            headers=headers, REMOTE_ADDR="76.76.21.21",  # IP da Vercel
        )

    def via_proxy(self, ip, secret=SECRET):
        return self.wrong_login(**{"X-DataFood-Proxy-Secret": secret, "X-DataFood-Client-IP": ip})

    def test_users_behind_proxy_have_separate_limits(self):
        for _ in range(5):
            self.assertEqual(401, self.via_proxy("200.1.1.1").status_code)
        self.assertEqual(429, self.via_proxy("200.1.1.1").status_code)
        self.assertEqual(401, self.via_proxy("200.2.2.2").status_code, "outro usuário não herda o limite")

    def test_wrong_secret_is_ignored(self):
        # segredo errado: trocar o IP forjado não escapa do limite da conexão
        for i in range(5):
            self.assertEqual(401, self.via_proxy(f"200.9.9.{i}", secret="chute").status_code)
        self.assertEqual(429, self.via_proxy("200.9.9.99", secret="chute").status_code)

    @override_settings(FRONTEND_PROXY_SECRET="")
    def test_without_configured_secret_header_is_ignored(self):
        for _ in range(5):
            self.via_proxy("200.1.1.1", secret="")
        self.assertEqual(429, self.via_proxy("200.3.3.3", secret="").status_code)
