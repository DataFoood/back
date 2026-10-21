from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import MessagingPreference, Promotion, PromotionDelivery
from .services import delivery_stats, public_url, render_text, whatsapp_url

MAX_SCHEDULE_AHEAD = timedelta(days=30)


class PromotionSerializer(serializers.ModelSerializer):
    """Gestão (dono/admin). Envio/agendamento têm rota própria: aqui o status
    é só leitura."""

    share_text = serializers.SerializerMethodField()
    whatsapp_url = serializers.SerializerMethodField()
    public_url = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Promotion
        fields = [
            "id", "restaurant", "title", "message", "coupon_code", "valid_until",
            "send_telegram", "send_email", "status", "scheduled_for",
            "dispatched_at", "sent_at", "created_at", "updated_at",
            "share_text", "whatsapp_url", "public_url", "stats",
        ]
        read_only_fields = [
            "id", "restaurant", "status", "scheduled_for", "dispatched_at",
            "sent_at", "created_at", "updated_at",
        ]

    def get_share_text(self, obj) -> str:
        return render_text(obj)

    def get_whatsapp_url(self, obj) -> str:
        return whatsapp_url(obj)

    def get_public_url(self, obj) -> str:
        return public_url(obj.restaurant)

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_stats(self, obj):
        # a listagem anota as contagens (sem N+1); fora dela, consulta
        if hasattr(obj, "stat_sent"):
            return {status: getattr(obj, f"stat_{status}") for status in PromotionDelivery.Status.values}
        return delivery_stats(obj)

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Informe um título.")
        return value

    def validate_message(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Escreva a mensagem da promoção.")
        return value

    def validate_valid_until(self, value):
        if value and value < timezone.localdate():
            raise serializers.ValidationError("A validade não pode estar no passado.")
        return value

    def validate(self, attrs):
        if self.instance and self.instance.status not in (
            Promotion.Status.DRAFT, Promotion.Status.SCHEDULED
        ):
            raise serializers.ValidationError("Promoção já enviada não pode ser editada.")
        return attrs


class PublicPromotionSerializer(serializers.ModelSerializer):
    """Vitrine na página do restaurante — sem dados de envio."""

    class Meta:
        model = Promotion
        fields = ["id", "title", "message", "coupon_code", "valid_until", "sent_at"]
        read_only_fields = fields


class SendSerializer(serializers.Serializer):
    """Vazio = enviar agora; com scheduled_for = agendar."""

    scheduled_for = serializers.DateTimeField(required=False, allow_null=True)

    def validate_scheduled_for(self, value):
        if value is None:
            return value
        now = timezone.now()
        if value <= now + timedelta(minutes=1):
            raise serializers.ValidationError("Agende para pelo menos alguns minutos à frente.")
        if value > now + MAX_SCHEDULE_AHEAD:
            raise serializers.ValidationError("Agende com no máximo 30 dias de antecedência.")
        return value


class MessagingPreferenceSerializer(serializers.ModelSerializer):
    telegram_linked = serializers.SerializerMethodField()

    class Meta:
        model = MessagingPreference
        fields = [
            "promotions_opt_in", "opted_in_at", "channel_email", "channel_telegram",
            "telegram_linked", "telegram_linked_at",
        ]
        read_only_fields = ["opted_in_at", "telegram_linked", "telegram_linked_at"]

    def get_telegram_linked(self, obj) -> bool:
        return bool(obj.telegram_chat_id)

    def update(self, instance, validated_data):
        turning_on = validated_data.get("promotions_opt_in") and not instance.promotions_opt_in
        if turning_on:
            instance.opted_in_at = timezone.now()
        return super().update(instance, validated_data)
