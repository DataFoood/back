import hashlib

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import User


@override_settings(
    PREMIUM_TEST_COUPON_SHA256=hashlib.sha256(b"TEST-ONLY-COUPON").hexdigest(),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class PremiumCouponTest(APITestCase):
    url = "/api/users/premium/redeem/"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="coupon@test.example", name="Teste", password="Testing12345")
        cls.other = User.objects.create_user(email="other-coupon@test.example", name="Outra", password="Testing12345")

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.user)

    def test_requires_authentication_and_valid_code(self):
        self.client.force_authenticate(None)
        self.assertEqual(401, self.client.post(self.url, {"code": "TEST-ONLY-COUPON"}).status_code)
        self.client.force_authenticate(self.user)
        for data in ({}, {"code": "wrong"}, {"code": "á"}, {"code": "x" * 81}):
            self.assertEqual(400, self.client.post(self.url, data, format="json").status_code)
        self.user.refresh_from_db()
        self.assertEqual(1, self.user.level)

    @override_settings(PREMIUM_TEST_COUPON_SHA256="")
    def test_disabled_coupon_does_not_grant_premium(self):
        self.assertEqual(503, self.client.post(self.url, {"code": "TEST-ONLY-COUPON"}).status_code)
        self.user.refresh_from_db()
        self.assertEqual(1, self.user.level)

    def test_unlimited_accounts_and_idempotent_redeem_without_privilege_or_consent_change(self):
        response = self.client.post(self.url, {"code": " TEST-ONLY-COUPON ", "user_id": self.other.pk, "level": 99}, format="json")
        self.assertEqual(200, response.status_code, response.data)
        self.assertEqual(2, response.data["level"])
        self.other.refresh_from_db()
        self.assertEqual(1, self.other.level)
        for user in (self.user, self.other):
            self.client.force_authenticate(user)
            for _ in range(2):
                self.assertEqual(200, self.client.post(self.url, {"code": "TEST-ONLY-COUPON"}).status_code)
            user.refresh_from_db()
            self.assertEqual(2, user.level)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
            self.assertFalse(user.allow_info)
            self.assertEqual("customer", user.role)

    def test_does_not_downgrade_an_existing_higher_level(self):
        self.user.level = 3
        self.user.save(update_fields=["level"])
        response = self.client.post(self.url, {"code": "TEST-ONLY-COUPON"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(3, response.data["level"])

    def test_throttles_attempts_without_limiting_total_redemptions(self):
        for _ in range(10):
            self.assertEqual(400, self.client.post(self.url, {"code": "wrong"}).status_code)
        self.assertEqual(429, self.client.post(self.url, {"code": "wrong"}).status_code)
