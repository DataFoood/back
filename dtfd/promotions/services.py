"""Regras de envio de promoções: público, texto, limites e disparo."""

import logging
from datetime import datetime, time, timedelta
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from restaurants.models import Restaurant, RestaurantFavorite
from users.models import User

from . import messengers
from .models import MessagingPreference, Promotion, PromotionDelivery

logger = logging.getLogger(__name__)

UNSUBSCRIBE_SALT = "promotions.unsubscribe"
# promoção "enviando" há mais que isso = worker morreu (ex.: máquina local
# desligada); o dispatcher retoma só as entregas ainda pendentes
STUCK_AFTER = timedelta(minutes=15)


class LimitExceeded(Exception):
    pass


# --- público ---------------------------------------------------------------
def recipients_for(restaurant: Restaurant):
    """Quem favoritou o restaurante E deu opt-in. Mesmo filter() = mesmo JOIN
    (o favorito ativo e o restaurante certo precisam ser a mesma linha)."""
    return (
        User.objects.filter(
            is_active=True,
            favorites__restaurant=restaurant,
            favorites__deleted_at__isnull=True,
            messaging_preference__promotions_opt_in=True,
        )
        .select_related("messaging_preference")
        .distinct()
        .order_by("id")
    )


def preference_of(user: User) -> MessagingPreference:
    # relação reversa (OneToOne) — os stubs do Django não a enxergam
    return user.messaging_preference  # type: ignore[attr-defined]


def channels_for(promotion: Promotion, user: User) -> list[str]:
    pref = preference_of(user)
    channels = []
    if (
        promotion.send_telegram and pref.channel_telegram and pref.telegram_chat_id
        and messengers.telegram_enabled()
    ):
        channels.append(PromotionDelivery.Channel.TELEGRAM)
    if promotion.send_email and pref.channel_email and user.email:
        channels.append(PromotionDelivery.Channel.EMAIL)
    return channels


def audience(restaurant: Restaurant) -> dict:
    """Contagens agregadas (nenhum dado pessoal) para o dono estimar o alcance."""
    base = recipients_for(restaurant)
    return {
        "favorites": RestaurantFavorite.objects.filter(restaurant=restaurant).count(),
        "opted_in": base.count(),
        "telegram": (
            base.filter(messaging_preference__channel_telegram=True)
            .exclude(messaging_preference__telegram_chat_id="").count()
            if messengers.telegram_enabled() else 0
        ),
        "email": base.filter(messaging_preference__channel_email=True).count(),
        "telegram_configured": messengers.telegram_enabled(),
    }


def estimated_messages(promotion: Promotion) -> int:
    return sum(len(channels_for(promotion, u)) for u in recipients_for(promotion.restaurant))


# --- texto -----------------------------------------------------------------
def public_url(restaurant: Restaurant) -> str:
    return f"{settings.FRONTEND_URL}/restaurante/{restaurant.slug}"


def render_text(promotion: Promotion) -> str:
    lines = [f"{promotion.restaurant.name}: {promotion.title}", "", promotion.message.strip()]
    if promotion.coupon_code:
        lines.append(f"\nCupom: {promotion.coupon_code}")
    if promotion.valid_until:
        lines.append(f"Válido até {promotion.valid_until.strftime('%d/%m/%Y')}")
    lines.append(f"\n{public_url(promotion.restaurant)}")
    return "\n".join(lines).strip()


def whatsapp_url(promotion: Promotion) -> str:
    """Link de compartilhamento: abre o WhatsApp do dono com o texto pronto
    para lista de transmissão, grupo ou status. Não expõe telefone de cliente."""
    return f"https://wa.me/?text={quote(render_text(promotion))}"


def unsubscribe_token(user: User) -> str:
    return signing.dumps({"u": user.pk}, salt=UNSUBSCRIBE_SALT)


def unsubscribe_url(user: User) -> str:
    return f"{settings.FRONTEND_URL}/promocoes/descadastrar?token={unsubscribe_token(user)}"


def unsubscribe(token: str) -> bool:
    try:
        data = signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return False
    updated = MessagingPreference.objects.filter(user_id=data.get("u")).update(
        promotions_opt_in=False
    )
    return updated > 0 or User.objects.filter(pk=data.get("u")).exists()


# --- limites ---------------------------------------------------------------
def _day_bounds(day):
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def check_daily_limit(restaurant: Restaurant, when: datetime, exclude_pk=None) -> None:
    """Máximo de promoções por restaurante por dia (enviadas ou agendadas no
    dia de `when`). Chame com o restaurante travado (select_for_update)."""
    start, end = _day_bounds(timezone.localtime(when).date())
    # all_objects: remover uma promoção enviada não devolve a cota do dia
    qs = Promotion.all_objects.filter(restaurant=restaurant).filter(
        Q(dispatched_at__gte=start, dispatched_at__lt=end)
        | Q(status=Promotion.Status.SCHEDULED, scheduled_for__gte=start, scheduled_for__lt=end)
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    limit = settings.PROMOTIONS_MAX_PER_DAY
    if qs.count() >= limit:
        raise LimitExceeded(f"Limite de {limit} promoções por dia para este restaurante.")


# --- transições ------------------------------------------------------------
def _lock_restaurant(promotion: Promotion) -> None:
    """Serializa envios/agendamentos do mesmo restaurante (limite diário sem TOCTOU)."""
    list(Restaurant.objects.select_for_update(of=("self",)).filter(promotions=promotion))


def dispatch_now(promotion: Promotion) -> Promotion:
    """rascunho/agendada -> enviando. Enfileira o envio após o commit."""
    from .tasks import send_promotion

    with transaction.atomic():
        _lock_restaurant(promotion)
        promotion = Promotion.objects.select_for_update().get(pk=promotion.pk)
        if promotion.status not in (Promotion.Status.DRAFT, Promotion.Status.SCHEDULED):
            raise LimitExceeded("Esta promoção já foi enviada.")
        now = timezone.now()
        check_daily_limit(promotion.restaurant, now, exclude_pk=promotion.pk)
        promotion.status = Promotion.Status.SENDING
        promotion.dispatched_at = now
        promotion.scheduled_for = None
        promotion.save(update_fields=["status", "dispatched_at", "scheduled_for", "updated_at"])
        transaction.on_commit(lambda pk=promotion.pk: send_promotion.delay(pk))
    return promotion


def schedule(promotion: Promotion, when: datetime) -> Promotion:
    with transaction.atomic():
        _lock_restaurant(promotion)
        promotion = Promotion.objects.select_for_update().get(pk=promotion.pk)
        if promotion.status not in (Promotion.Status.DRAFT, Promotion.Status.SCHEDULED):
            raise LimitExceeded("Esta promoção já foi enviada.")
        check_daily_limit(promotion.restaurant, when, exclude_pk=promotion.pk)
        promotion.status = Promotion.Status.SCHEDULED
        promotion.scheduled_for = when
        promotion.save(update_fields=["status", "scheduled_for", "updated_at"])
    return promotion


def claim_due() -> list[int]:
    """Agendadas vencidas -> enviando (update condicional: dois beats não
    pegam a mesma). Inclui as travadas em 'enviando' para retomar."""
    now = timezone.now()
    due = list(
        Promotion.objects.filter(
            status=Promotion.Status.SCHEDULED, scheduled_for__lte=now
        ).values_list("pk", flat=True)
    )
    claimed = [
        pk for pk in due
        if Promotion.objects.filter(pk=pk, status=Promotion.Status.SCHEDULED).update(
            status=Promotion.Status.SENDING, dispatched_at=now
        )
    ]
    stuck = list(
        Promotion.objects.filter(
            status=Promotion.Status.SENDING, dispatched_at__lt=now - STUCK_AFTER
        ).values_list("pk", flat=True)
    )
    return claimed + stuck


# --- envio -----------------------------------------------------------------
def deliver(promotion_id: int) -> dict:
    """Envia a promoção para o público atual. Idempotente por (promoção,
    usuário, canal); falha num destinatário não interrompe os outros."""
    promotion = (
        Promotion.objects.select_related("restaurant").filter(pk=promotion_id).first()
    )
    if promotion is None or promotion.status != Promotion.Status.SENDING:
        return {}

    text = render_text(promotion)
    subject = f"{promotion.restaurant.name}: {promotion.title}"[:150]
    recipients = list(recipients_for(promotion.restaurant))

    # anti-spam: cada pessoa recebe no máximo N promoções (de qualquer
    # restaurante) por 24h
    since = timezone.now() - timedelta(hours=24)
    received = dict(
        PromotionDelivery.objects.filter(
            user__in=recipients, status=PromotionDelivery.Status.SENT, sent_at__gte=since
        )
        .exclude(promotion=promotion)
        .values("user")
        .annotate(n=Count("promotion", distinct=True))
        .values_list("user", "n")
    )
    cap = settings.PROMOTIONS_USER_DAILY_CAP

    for user in recipients:
        capped = received.get(user.pk, 0) >= cap
        for channel in channels_for(promotion, user):
            delivery, _ = PromotionDelivery.objects.get_or_create(
                promotion=promotion, user=user, channel=channel
            )
            claimed = PromotionDelivery.objects.filter(
                pk=delivery.pk, status=PromotionDelivery.Status.PENDING
            ).update(status=PromotionDelivery.Status.SENDING)
            if not claimed:
                continue
            if capped:
                _finish(delivery, PromotionDelivery.Status.SKIPPED, "limite diário de promoções")
                continue
            try:
                if channel == PromotionDelivery.Channel.TELEGRAM:
                    messengers.send_telegram(preference_of(user).telegram_chat_id, text)
                else:
                    footer = f"\n\n--\nNão quer mais receber? {unsubscribe_url(user)}"
                    messengers.send_email(user.email, subject, text + footer, unsubscribe_url(user))
            except messengers.RecipientGone as exc:
                # bloqueou o bot: desvincula para não tentar de novo
                MessagingPreference.objects.filter(user=user).update(
                    telegram_chat_id="", telegram_linked_at=None
                )
                _finish(delivery, PromotionDelivery.Status.FAILED, str(exc))
            except messengers.DeliveryError as exc:
                logger.warning("promoção %s: falha em %s", promotion.pk, channel)
                _finish(delivery, PromotionDelivery.Status.FAILED, str(exc))
            else:
                _finish(delivery, PromotionDelivery.Status.SENT)

    Promotion.objects.filter(pk=promotion.pk).update(
        status=Promotion.Status.SENT, sent_at=timezone.now()
    )
    return delivery_stats(promotion)


def _finish(delivery, status, error=""):
    PromotionDelivery.objects.filter(pk=delivery.pk).update(
        status=status, error=error[:255],
        sent_at=timezone.now() if status == PromotionDelivery.Status.SENT else None,
    )


def delivery_stats(promotion: Promotion) -> dict:
    stats = {s: 0 for s in PromotionDelivery.Status.values}
    for row in PromotionDelivery.objects.filter(promotion=promotion).values("status").annotate(n=Count("id")):
        stats[row["status"]] = row["n"]
    return stats
