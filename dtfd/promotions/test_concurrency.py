from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from restaurants.models import Restaurant
from users.models import User
from .models import Promotion, PromotionReservation
from .services import reserve_recipient


@override_settings(PROMOTIONS_USER_DAILY_CAP=1)
class ReservationConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="quota@test.example", name="Quota", password="Test12345")
        restaurant = Restaurant.objects.create(name="Quota", slug="quota")
        self.promos = [Promotion.objects.create(restaurant=restaurant, title=str(i), message="Teste") for i in range(2)]

    def test_independent_connections_cannot_reserve_two_campaigns(self):
        barrier = Barrier(2)

        def reserve(pk):
            close_old_connections()
            try:
                promo = Promotion.objects.get(pk=pk)
                barrier.wait(timeout=10)
                return reserve_recipient(promo, self.user.pk)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, [p.pk for p in self.promos]))
        self.assertEqual(1, sum(results))
        self.assertEqual(1, PromotionReservation.objects.count())

    def test_channels_share_reservation_and_window_expires(self):
        self.assertTrue(reserve_recipient(self.promos[0], self.user.pk))
        self.assertTrue(reserve_recipient(self.promos[0], self.user.pk))
        self.assertFalse(reserve_recipient(self.promos[1], self.user.pk))
        PromotionReservation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(reserve_recipient(self.promos[1], self.user.pk))
