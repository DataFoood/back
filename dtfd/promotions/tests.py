from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from urllib.parse import unquote

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from preferences.models import SearchHistory
from restaurants.models import Restaurant, RestaurantFavorite
from users.models import User

from . import infra, messengers, services, telegram
from .models import MessagingPreference, Promotion, PromotionDelivery

TELEGRAM_ON = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_BOT_USERNAME": "datafood_bot"}


def make_user(email, role=User.Role.CUSTOMER, **extra):
    return User.objects.create_user(
        email=email, password="SenhaForte123", name=email.split("@")[0], role=role, **extra
    )


def subscribe(user, restaurant, telegram_chat="", **prefs):
    RestaurantFavorite.objects.create(user=user, restaurant=restaurant)
    return MessagingPreference.objects.create(
        user=user, promotions_opt_in=True, telegram_chat_id=telegram_chat, **prefs
    )


class Base(APITestCase):
    def setUp(self):
        cache.clear()  # throttle do descadastro vive no Redis
        self.owner = make_user("dono@dtfd.com", role=User.Role.OWNER)
        self.restaurant = Restaurant.objects.create(owner=self.owner, name="Cantina", slug="cantina")
        self.base = f"/api/restaurants/{self.restaurant.pk}/promotions/"

    def make_promo(self, **extra):
        data = {"title": "Rodízio", "message": "Pizza em dobro hoje", **extra}
        return Promotion.objects.create(restaurant=self.restaurant, created_by=self.owner, **data)


# ---------------------------------------------------------------------------
# CRUD + permissão
# ---------------------------------------------------------------------------
class PromotionCrudTest(Base):
    def test_owner_creates_draft(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.base, {"title": " Rodízio ", "message": "Pizza", "coupon_code": "PIZZA10"}, format="json"
        )
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        body = response.json()
        self.assertEqual("draft", body["status"])
        self.assertEqual("Rodízio", body["title"])
        self.assertIn("Cupom: PIZZA10", body["share_text"])
        self.assertTrue(body["whatsapp_url"].startswith("https://wa.me/?text="))
        self.assertIn("/restaurante/cantina", unquote(body["whatsapp_url"]))

    def test_status_in_payload_is_ignored(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.base, {"title": "x", "message": "y", "status": "sent"}, format="json")
        self.assertEqual("draft", response.json()["status"])

    def test_other_user_forbidden(self):
        self.make_promo()
        self.client.force_authenticate(make_user("outro@dtfd.com"))
        self.assertEqual(status.HTTP_403_FORBIDDEN, self.client.get(self.base).status_code)
        response = self.client.post(self.base, {"title": "x", "message": "y"}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_anonymous_unauthorized(self):
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, self.client.get(self.base).status_code)

    def test_admin_can_manage(self):
        admin = User.objects.create_superuser(email="adm@dtfd.com", password="SenhaForte123", name="Adm")
        self.client.force_authenticate(admin)
        self.assertEqual(status.HTTP_200_OK, self.client.get(self.base).status_code)

    def test_past_valid_until_rejected(self):
        self.client.force_authenticate(self.owner)
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.client.post(self.base, {"title": "x", "message": "y", "valid_until": yesterday}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("valid_until", response.json())

    def test_blank_message_rejected(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.base, {"title": "x", "message": "   "}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_sent_promotion_is_read_only(self):
        promo = self.make_promo(status=Promotion.Status.SENT)
        self.client.force_authenticate(self.owner)
        response = self.client.patch(f"{self.base}{promo.pk}/", {"title": "novo"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_delete_is_soft_and_hides_from_public(self):
        promo = self.make_promo(status=Promotion.Status.SENT, sent_at=timezone.now())
        self.client.force_authenticate(self.owner)
        self.assertEqual(status.HTTP_204_NO_CONTENT, self.client.delete(f"{self.base}{promo.pk}/").status_code)
        self.assertTrue(Promotion.all_objects.filter(pk=promo.pk, deleted_at__isnull=False).exists())
        self.client.force_authenticate(None)
        self.assertEqual([], self.client.get(f"{self.base}active/").json())

    def test_list_stats_without_n_plus_one(self):
        for i in range(5):
            self.make_promo(title=f"p{i}")
        self.client.force_authenticate(self.owner)
        # permissão (restaurante + dono) + lista com as contagens anotadas;
        # não cresce com o número de promoções
        with self.assertNumQueries(3):
            response = self.client.get(self.base)
        self.assertEqual(5, len(response.json()))


class ActivePromotionsTest(Base):
    def test_public_lists_only_sent_and_valid(self):
        today = timezone.localdate()
        self.make_promo(title="rascunho")
        self.make_promo(title="vencida", status=Promotion.Status.SENT, valid_until=today - timedelta(days=1))
        self.make_promo(title="ativa", status=Promotion.Status.SENT, sent_at=timezone.now(), valid_until=today)
        response = self.client.get(f"{self.base}active/")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(["ativa"], [p["title"] for p in response.json()])
        self.assertNotIn("stats", response.json()[0])


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------
@override_settings(**TELEGRAM_ON)
class PromotionSendTest(Base):
    def setUp(self):
        super().setUp()
        self.fan = make_user("fan@dtfd.com")
        subscribe(self.fan, self.restaurant, telegram_chat="555")
        # favoritou mas não deu opt-in
        self.quiet = make_user("quiet@dtfd.com")
        RestaurantFavorite.objects.create(user=self.quiet, restaurant=self.restaurant)
        # opt-in mas não favoritou
        self.other = make_user("other@dtfd.com")
        MessagingPreference.objects.create(user=self.other, promotions_opt_in=True)

    def send(self, promo, **body):
        self.client.force_authenticate(self.owner)
        with patch("promotions.messengers.telegram_call") as tg, self.captureOnCommitCallbacks(execute=True):
            tg.return_value = {"ok": True}
            response = self.client.post(f"{self.base}{promo.pk}/send/", body, format="json")
        return response, tg

    def test_send_now_reaches_only_opted_in_favoriters(self):
        promo = self.make_promo()
        response, tg = self.send(promo)
        self.assertEqual(status.HTTP_202_ACCEPTED, response.status_code)
        promo.refresh_from_db()
        self.assertEqual(Promotion.Status.SENT, promo.status)
        self.assertEqual(1, tg.call_count)
        self.assertEqual("555", tg.call_args.args[1]["chat_id"])
        self.assertEqual(["fan@dtfd.com"], [m.to[0] for m in mail.outbox])
        self.assertIn("/promocoes/descadastrar?token=", mail.outbox[0].body)
        self.assertIn("List-Unsubscribe", mail.outbox[0].extra_headers)
        self.assertEqual(2, PromotionDelivery.objects.filter(status="sent").count())

    def test_channel_toggles_respected(self):
        MessagingPreference.objects.filter(user=self.fan).update(channel_email=False)
        promo = self.make_promo(send_telegram=False)
        self.send(promo)
        self.assertEqual(0, len(mail.outbox))
        self.assertFalse(PromotionDelivery.objects.exists())
        promo.refresh_from_db()
        self.assertEqual(Promotion.Status.SENT, promo.status)  # publicada (vitrine/whatsapp)

    def test_cannot_send_twice(self):
        promo = self.make_promo()
        self.send(promo)
        response, tg = self.send(promo)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertEqual(0, tg.call_count)

    def test_rerun_is_idempotent(self):
        promo = self.make_promo()
        self.send(promo)
        Promotion.objects.filter(pk=promo.pk).update(status=Promotion.Status.SENDING)
        with patch("promotions.messengers.telegram_call") as tg:
            services.deliver(promo.pk)
        self.assertEqual(0, tg.call_count)
        self.assertEqual(1, len(mail.outbox))

    @override_settings(PROMOTIONS_MAX_PER_DAY=1)
    def test_daily_limit_per_restaurant(self):
        self.send(self.make_promo())
        response, _ = self.send(self.make_promo(title="outra"))
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("Limite", response.json()["detail"])

    @override_settings(PROMOTIONS_MAX_PER_DAY=1)
    def test_deleting_sent_does_not_free_daily_quota(self):
        promo = self.make_promo()
        self.send(promo)
        self.client.delete(f"{self.base}{promo.pk}/")
        response, _ = self.send(self.make_promo(title="outra"))
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    @override_settings(PROMOTIONS_USER_DAILY_CAP=1, PROMOTIONS_MAX_PER_DAY=5)
    def test_user_daily_cap_skips(self):
        self.send(self.make_promo())
        self.send(self.make_promo(title="segunda"))
        self.assertEqual(1, len(mail.outbox))
        self.assertEqual(2, PromotionDelivery.objects.filter(status="skipped").count())

    def test_blocked_bot_unlinks_and_others_continue(self):
        promo = self.make_promo()
        self.client.force_authenticate(self.owner)
        with patch(
            "promotions.messengers.telegram_call", side_effect=messengers.RecipientGone("blocked")
        ), self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"{self.base}{promo.pk}/send/", {}, format="json")
        self.assertEqual("", MessagingPreference.objects.get(user=self.fan).telegram_chat_id)
        self.assertEqual(1, len(mail.outbox))  # e-mail seguiu
        self.assertTrue(PromotionDelivery.objects.filter(channel="telegram", status="failed").exists())

    def test_telegram_off_without_token(self):
        with self.settings(TELEGRAM_BOT_TOKEN=""):
            self.send(self.make_promo())
        self.assertFalse(PromotionDelivery.objects.filter(channel="telegram").exists())

    def test_schedule_then_dispatcher_sends(self):
        promo = self.make_promo()
        when = timezone.now() + timedelta(hours=2)
        response, tg = self.send(promo, scheduled_for=when.isoformat())
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual("scheduled", response.json()["status"])
        self.assertEqual(0, tg.call_count)
        self.assertEqual([], services.claim_due())
        Promotion.objects.filter(pk=promo.pk).update(scheduled_for=timezone.now() - timedelta(minutes=1))
        with patch("promotions.messengers.telegram_call", return_value={"ok": True}):
            from .tasks import dispatch_scheduled

            with patch("promotions.tasks.send_promotion.delay", side_effect=services.deliver):
                self.assertEqual(1, dispatch_scheduled())
        promo.refresh_from_db()
        self.assertEqual(Promotion.Status.SENT, promo.status)
        self.assertEqual(1, len(mail.outbox))

    def test_schedule_in_past_rejected(self):
        response, _ = self.send(self.make_promo(), scheduled_for=timezone.now().isoformat())
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_unschedule(self):
        promo = self.make_promo(status=Promotion.Status.SCHEDULED, scheduled_for=timezone.now() + timedelta(hours=1))
        self.client.force_authenticate(self.owner)
        response = self.client.post(f"{self.base}{promo.pk}/unschedule/")
        self.assertEqual("draft", response.json()["status"])

    def test_stuck_sending_is_resumed(self):
        promo = self.make_promo(status=Promotion.Status.SENDING, dispatched_at=timezone.now() - timedelta(hours=1))
        self.assertEqual([promo.pk], services.claim_due())

    def test_audience_counts(self):
        self.client.force_authenticate(self.owner)
        body = self.client.get(f"{self.base}audience/").json()
        self.assertEqual({"favorites": 2, "opted_in": 1, "telegram": 1, "email": 1, "telegram_configured": True}, body)


# ---------------------------------------------------------------------------
# Preferências / Telegram / descadastro
# ---------------------------------------------------------------------------
class PreferencesTest(Base):
    def test_opt_in_records_consent_time(self):
        user = make_user("c@dtfd.com")
        self.client.force_authenticate(user)
        self.assertFalse(self.client.get("/api/promotions/preferences/").json()["promotions_opt_in"])
        body = self.client.patch("/api/promotions/preferences/", {"promotions_opt_in": True}, format="json").json()
        self.assertTrue(body["promotions_opt_in"])
        self.assertIsNotNone(body["opted_in_at"])

    def test_unsubscribe_token(self):
        user = make_user("c@dtfd.com")
        MessagingPreference.objects.create(user=user, promotions_opt_in=True)
        token = services.unsubscribe_token(user)
        response = self.client.post("/api/promotions/unsubscribe/", {"token": token}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertFalse(MessagingPreference.objects.get(user=user).promotions_opt_in)

    def test_unsubscribe_forged_token(self):
        response = self.client.post("/api/promotions/unsubscribe/", {"token": "1:abc"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_telegram_link_unconfigured(self):
        self.client.force_authenticate(make_user("c@dtfd.com"))
        with self.settings(TELEGRAM_BOT_TOKEN=""):
            response = self.client.post("/api/promotions/preferences/telegram/")
        self.assertEqual(status.HTTP_503_SERVICE_UNAVAILABLE, response.status_code)

    @override_settings(**TELEGRAM_ON)
    def test_telegram_link_flow(self):
        user = make_user("c@dtfd.com")
        self.client.force_authenticate(user)
        url = self.client.post("/api/promotions/preferences/telegram/").json()["url"]
        self.assertTrue(url.startswith("https://t.me/datafood_bot?start="))
        token = url.split("start=")[1]
        with patch("promotions.messengers.telegram_call") as tg:
            telegram.handle_update({"message": {"chat": {"id": 42, "type": "private"}, "text": f"/start {token}"}})
            self.assertIn("Pronto", tg.call_args.args[1]["text"])
        pref = MessagingPreference.objects.get(user=user)
        self.assertEqual("42", pref.telegram_chat_id)
        self.assertEqual("", pref.telegram_link_token, "token é de uso único")
        self.assertTrue(self.client.get("/api/promotions/preferences/").json()["telegram_linked"])

        with patch("promotions.messengers.telegram_call"):
            telegram.handle_update({"message": {"chat": {"id": 42, "type": "private"}, "text": "/sair"}})
        self.assertEqual("", MessagingPreference.objects.get(user=user).telegram_chat_id)

    @override_settings(**TELEGRAM_ON)
    def test_telegram_rejects_expired_token_and_groups(self):
        user = make_user("c@dtfd.com")
        pref = MessagingPreference.objects.create(
            user=user, telegram_link_token="tok", telegram_link_expires_at=timezone.now() - timedelta(minutes=1)
        )
        with patch("promotions.messengers.telegram_call"):
            telegram.handle_update({"message": {"chat": {"id": 1, "type": "private"}, "text": "/start tok"}})
            pref.telegram_link_expires_at = timezone.now() + timedelta(minutes=5)
            pref.save()
            telegram.handle_update({"message": {"chat": {"id": 2, "type": "group"}, "text": "/start tok"}})
        self.assertEqual("", MessagingPreference.objects.get(user=user).telegram_chat_id)

    @override_settings(**TELEGRAM_ON)
    def test_poll_advances_offset(self):
        updates = {"ok": True, "result": [{"update_id": 10, "message": {}}, {"update_id": 11, "message": {}}]}
        with patch("promotions.messengers.telegram_call", return_value=updates) as tg:
            self.assertEqual(2, telegram.poll())
            telegram.poll()
        self.assertEqual(12, tg.call_args.args[1]["offset"])


# ---------------------------------------------------------------------------
# Sugestão de infra no fim de semana
# ---------------------------------------------------------------------------
class InfraSuggestionTest(TestCase):
    def setUp(self):
        self.owner = make_user("dono@dtfd.com", role=User.Role.OWNER)

    def test_upcoming_weekend(self):
        self.assertEqual(date(2026, 10, 23), infra.upcoming_weekend(date(2026, 10, 20)))  # terça
        self.assertEqual(date(2026, 10, 23), infra.upcoming_weekend(date(2026, 10, 25)))  # domingo

    @override_settings(LOCAL_CAPACITY_SEARCHES_PER_DAY=10)
    def test_recommends_when_weekend_peak_exceeds_capacity(self):
        user = make_user("c@dtfd.com")
        today = timezone.localdate()
        last_saturday = today - timedelta(days=(today.weekday() - 5) % 7 or 7)
        at = timezone.make_aware(datetime.combine(last_saturday, time(20, 0)))
        rows = SearchHistory.objects.bulk_create(SearchHistory(user=user, query="pizza") for _ in range(60))
        SearchHistory.objects.filter(pk__in=[r.pk for r in rows]).update(created_at=at)

        data = infra.suggestion()
        self.assertEqual("hire", data["level"])  # 60/4 semanas = 15/dia > 10
        self.assertTrue(data["recommend"])
        self.assertEqual(15, data["projected"]["searches_peak_day"])
        self.assertEqual(54, data["suggested_window"]["hours"])
        self.assertTrue(data["reasons"])

    def test_quiet_platform_is_ok(self):
        data = infra.suggestion()
        self.assertEqual("ok", data["level"])
        self.assertFalse(data["recommend"])

    def test_endpoint_permissions(self):
        url = "/api/promotions/infra-suggestion/"
        self.client.force_login(make_user("c@dtfd.com"))
        self.assertEqual(status.HTTP_403_FORBIDDEN, self.client.get(url).status_code)
        self.client.force_login(self.owner)
        self.assertEqual(status.HTTP_200_OK, self.client.get(url).status_code)
