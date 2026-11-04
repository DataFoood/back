from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from restaurants.models import Restaurant, RestaurantFavorite
from users.models import User
from . import services, messengers
from .models import MessagingPreference, Promotion, PromotionDelivery, PromotionOutbox


class RecoveryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="recovery@test.example", name="Recovery", password="Test12345")
        self.r = Restaurant.objects.create(name="Recovery", slug="recovery")
        RestaurantFavorite.objects.create(user=self.user, restaurant=self.r)
        MessagingPreference.objects.create(user=self.user, promotions_opt_in=True, channel_telegram=False)
        self.p = Promotion.objects.create(restaurant=self.r, title="Oferta", message="Teste", status="sending")

    def test_total_failure_does_not_report_sent(self):
        with patch("promotions.messengers.send_email", side_effect=messengers.DeliveryError("recusado")):
            services.deliver(self.p.pk)
        self.p.refresh_from_db()
        self.assertEqual("failed", self.p.status)

    def test_transient_failure_is_retried_only_when_due(self):
        with patch("promotions.messengers.send_email", side_effect=messengers.TransientDeliveryError("indisponível")) as send:
            services.deliver(self.p.pk)
            services.deliver(self.p.pk)
        self.assertEqual(1, send.call_count)
        delivery = PromotionDelivery.objects.get(promotion=self.p)
        self.assertEqual("pending", delivery.status)
        self.assertGreater(delivery.next_attempt_at, timezone.now())
        self.assertTrue(PromotionOutbox.objects.filter(promotion=self.p).exists())
        PromotionDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        with patch("promotions.messengers.send_email") as send:
            services.deliver(self.p.pk)
        self.assertEqual(1, send.call_count)
        self.p.refresh_from_db()
        self.assertEqual("sent", self.p.status)
        self.assertFalse(PromotionOutbox.objects.filter(promotion=self.p).exists())

    def test_unknown_acceptance_is_not_automatically_retried(self):
        with patch("promotions.messengers.send_email", side_effect=messengers.UnknownDeliveryError("timeout")) as send:
            services.deliver(self.p.pk)
            services.deliver(self.p.pk)
        self.assertEqual(1, send.call_count)
        self.assertEqual("unknown", PromotionDelivery.objects.get().status)

    def test_consent_removed_before_retry_blocks_send(self):
        with patch("promotions.messengers.send_email", side_effect=messengers.TransientDeliveryError("offline")):
            services.deliver(self.p.pk)
        MessagingPreference.objects.filter(user=self.user).update(promotions_opt_in=False)
        with patch("promotions.messengers.send_email") as send:
            services.deliver(self.p.pk)
        self.assertFalse(send.called)
        self.assertEqual("skipped", PromotionDelivery.objects.get().status)
        self.assertFalse(PromotionOutbox.objects.filter(promotion=self.p).exists())

    def test_interrupted_delivery_is_not_repeated(self):
        PromotionDelivery.objects.create(promotion=self.p, user=self.user, channel="email", status="sending")
        with patch("promotions.messengers.send_email") as send:
            services.deliver(self.p.pk)
        self.assertFalse(send.called)
        self.assertEqual("unknown", PromotionDelivery.objects.get().status)

    def test_queue_failure_preserves_durable_intent(self):
        self.p.status = "draft"
        self.p.save()
        with patch("promotions.tasks.send_promotion.delay", side_effect=ConnectionError), self.captureOnCommitCallbacks(execute=True):
            services.dispatch_now(self.p)
        self.assertTrue(PromotionOutbox.objects.filter(promotion=self.p).exists())
        self.assertIn(self.p.pk, services.claim_due())

    def test_provider_pause_is_respected(self):
        error = messengers.TransientDeliveryError("429")
        error.retry_after = 3600
        with patch("promotions.messengers.send_email", side_effect=error):
            services.deliver(self.p.pk)
        self.assertGreaterEqual(PromotionDelivery.objects.get().next_attempt_at, timezone.now() + timedelta(minutes=59))

    def test_three_transient_attempts_finish_as_failed(self):
        with patch("promotions.messengers.send_email", side_effect=messengers.TransientDeliveryError("offline")) as send:
            for _ in range(3):
                PromotionDelivery.objects.filter(promotion=self.p).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
                services.deliver(self.p.pk)
        self.assertEqual(3, send.call_count)
        self.p.refresh_from_db()
        self.assertEqual("failed", self.p.status)
        self.assertFalse(PromotionOutbox.objects.filter(promotion=self.p).exists())

    def test_partial_failure_is_distinct_from_success(self):
        MessagingPreference.objects.filter(user=self.user).update(channel_telegram=True, telegram_chat_id="42")
        with self.settings(TELEGRAM_BOT_TOKEN="test"), patch("promotions.messengers.send_telegram", side_effect=messengers.DeliveryError("recusado")), patch("promotions.messengers.send_email"):
            services.deliver(self.p.pk)
        self.p.refresh_from_db()
        self.assertEqual("partial", self.p.status)
