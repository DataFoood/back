from django.conf import settings
from django.db import models

from utils import AbstractAudit


class MessagingPreference(models.Model):
    """Opt-in do usuário para receber promoções (LGPD: consentimento próprio,
    separado do `allow_info`). Só recebe quem também favoritou o restaurante.
    Criado sob demanda (get_or_create) — ausência = sem opt-in."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messaging_preference"
    )
    promotions_opt_in = models.BooleanField(default=False)
    # prova do consentimento (quando ligou)
    opted_in_at = models.DateTimeField(null=True, blank=True)
    channel_email = models.BooleanField(default=True)
    channel_telegram = models.BooleanField(default=True)

    # Telegram: o chat_id só existe depois que o usuário abre o bot pelo link
    # de vínculo (/start <token>). Token de uso único com validade curta.
    telegram_chat_id = models.CharField(max_length=32, blank=True)
    telegram_linked_at = models.DateTimeField(null=True, blank=True)
    telegram_link_token = models.CharField(max_length=64, blank=True, db_index=True)
    telegram_link_expires_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"messaging #{self.pk} opt_in={self.promotions_opt_in}"


class Promotion(AbstractAudit):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SCHEDULED = "scheduled", "Agendada"
        SENDING = "sending", "Enviando"
        SENT = "sent", "Enviada"

    restaurant = models.ForeignKey(
        "restaurants.Restaurant", on_delete=models.CASCADE, related_name="promotions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    title = models.CharField(max_length=120)
    message = models.TextField(max_length=1000)
    coupon_code = models.CharField(max_length=40, blank=True)
    valid_until = models.DateField(null=True, blank=True)

    # WhatsApp não entra aqui: é por link de compartilhamento (o dono dispara
    # pelo próprio WhatsApp), sempre disponível no serializer.
    send_telegram = models.BooleanField(default=True)
    send_email = models.BooleanField(default=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    # dispatched_at = começou a enviar (conta no limite diário); sent_at = terminou
    dispatched_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [models.Index(fields=["status", "scheduled_for"])]

    def __str__(self):
        return self.title


class PromotionDelivery(models.Model):
    """Uma mensagem (promoção x usuário x canal). A unicidade torna o envio
    idempotente: reprocessar a promoção não manda de novo pra quem já recebeu."""

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        EMAIL = "email", "E-mail"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        # reservada por um worker; se ele morrer aqui, não reenviamos
        # (melhor perder uma mensagem do que mandar em dobro)
        SENDING = "sending", "Enviando"
        SENT = "sent", "Enviada"
        FAILED = "failed", "Falhou"
        SKIPPED = "skipped", "Ignorada"

    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promotion_deliveries"
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["promotion", "user", "channel"], name="unique_promotion_delivery"
            )
        ]
        indexes = [models.Index(fields=["status", "sent_at"])]

    def __str__(self):
        return f"{self.channel} {self.status}"
