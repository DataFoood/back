from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from restaurants.models import Restaurant

from . import infra, messengers, services, telegram
from .models import MessagingPreference, Promotion, PromotionDelivery
from .permissions import IsRestaurantManager
from .serializers import (
    MessagingPreferenceSerializer,
    PromotionSerializer,
    PublicPromotionSerializer,
    SendSerializer,
)

STAT_ANNOTATIONS = {
    f"stat_{s}": Count("deliveries", filter=Q(deliveries__status=s))
    for s in PromotionDelivery.Status.values
}


def _managed_promotions(view):
    return (
        Promotion.objects.filter(restaurant_id=view.kwargs["restaurant_pk"])
        .select_related("restaurant")
        .annotate(**STAT_ANNOTATIONS)
        .order_by("-created_at", "id")
    )


class PromotionListCreateView(ListCreateAPIView):
    """GET/POST /api/restaurants/<restaurant_pk>/promotions/ — dono/admin.
    Cria sempre como rascunho; enviar/agendar é em .../send/."""
    serializer_class = PromotionSerializer
    permission_classes = [IsRestaurantManager]

    def get_queryset(self):
        return _managed_promotions(self)

    def perform_create(self, serializer):
        restaurant = get_object_or_404(Restaurant, pk=self.kwargs["restaurant_pk"])
        serializer.save(restaurant=restaurant, created_by=self.request.user)


class PromotionDetailView(RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE (soft) de uma promoção. Editar só antes do envio;
    remover tira da vitrine (não 'desenvia' mensagens)."""
    serializer_class = PromotionSerializer
    permission_classes = [IsRestaurantManager]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return _managed_promotions(self)

    def perform_destroy(self, instance):
        if instance.status == Promotion.Status.SENDING:
            raise ValidationError({"detail": "Aguarde o envio terminar para remover."})
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


class PromotionSendView(APIView):
    """POST .../promotions/<pk>/send/ — {} envia agora; {scheduled_for}
    agenda. Respeita o limite diário por restaurante."""
    permission_classes = [IsRestaurantManager]

    @extend_schema(request=SendSerializer, responses={202: PromotionSerializer, 200: PromotionSerializer})
    def post(self, request, restaurant_pk, pk):
        promotion = get_object_or_404(Promotion, pk=pk, restaurant_id=restaurant_pk)
        payload = SendSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        when = payload.validated_data.get("scheduled_for")
        try:
            if when:
                promotion = services.schedule(promotion, when)
            else:
                promotion = services.dispatch_now(promotion)
        except services.LimitExceeded as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        fresh = _managed_promotions(self).get(pk=promotion.pk)
        return Response(
            PromotionSerializer(fresh).data,
            status=status.HTTP_200_OK if when else status.HTTP_202_ACCEPTED,
        )


class PromotionUnscheduleView(APIView):
    """POST .../promotions/<pk>/unschedule/ — agendada volta a rascunho."""
    permission_classes = [IsRestaurantManager]

    @extend_schema(request=None, responses=PromotionSerializer)
    def post(self, request, restaurant_pk, pk):
        updated = Promotion.objects.filter(
            pk=pk, restaurant_id=restaurant_pk, status=Promotion.Status.SCHEDULED
        ).update(status=Promotion.Status.DRAFT, scheduled_for=None, updated_at=timezone.now())
        if not updated:
            return Response({"detail": "Promoção não está agendada."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PromotionSerializer(_managed_promotions(self).get(pk=pk)).data)


class PromotionAudienceView(APIView):
    """GET .../promotions/audience/ — quantas pessoas cada canal alcança."""
    permission_classes = [IsRestaurantManager]

    @extend_schema(
        responses=inline_serializer(
            "PromotionAudience",
            {
                "favorites": serializers.IntegerField(),
                "opted_in": serializers.IntegerField(),
                "telegram": serializers.IntegerField(),
                "email": serializers.IntegerField(),
                "telegram_configured": serializers.BooleanField(),
            },
        )
    )
    def get(self, request, restaurant_pk):
        restaurant = get_object_or_404(Restaurant, pk=restaurant_pk)
        return Response(services.audience(restaurant))


class ActivePromotionsView(ListAPIView):
    """GET /api/restaurants/<restaurant_pk>/promotions/active/ — público,
    paginado: promoções enviadas e dentro da validade (vitrine)."""
    serializer_class = PublicPromotionSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        today = timezone.localdate()
        return (
            Promotion.objects.filter(
                restaurant_id=self.kwargs["restaurant_pk"],
                restaurant__deleted_at__isnull=True,
                status=Promotion.Status.SENT,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
            .order_by("-sent_at", "-id")
        )


# ---------------------------------------------------------------------------
# Preferências do cliente
# ---------------------------------------------------------------------------
class MessagingPreferenceView(APIView):
    """GET/PATCH /api/promotions/preferences/ — opt-in e canais do usuário."""
    permission_classes = [IsAuthenticated]

    def _pref(self, request):
        pref, _ = MessagingPreference.objects.get_or_create(user=request.user)
        return pref

    @extend_schema(responses=MessagingPreferenceSerializer)
    def get(self, request):
        return Response(MessagingPreferenceSerializer(self._pref(request)).data)

    @extend_schema(request=MessagingPreferenceSerializer, responses=MessagingPreferenceSerializer)
    def patch(self, request):
        serializer = MessagingPreferenceSerializer(self._pref(request), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TelegramLinkView(APIView):
    """POST /api/promotions/preferences/telegram/ — gera o link do bot (15 min).
    DELETE — desvincula o Telegram desta conta."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "TelegramLink", {"url": serializers.URLField(), "expires_at": serializers.DateTimeField()}
        ),
    )
    def post(self, request):
        if not (messengers.telegram_enabled() and settings.TELEGRAM_BOT_USERNAME):
            return Response(
                {"detail": "Telegram não está configurado neste servidor."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        pref, _ = MessagingPreference.objects.get_or_create(user=request.user)
        url, expires_at = telegram.link_url(pref)
        return Response({"url": url, "expires_at": expires_at})

    @extend_schema(request=None, responses={204: None})
    def delete(self, request):
        MessagingPreference.objects.filter(user=request.user).update(
            telegram_chat_id="", telegram_linked_at=None, telegram_link_token=""
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class UnsubscribeView(APIView):
    """POST /api/promotions/unsubscribe/ {token} — público (link do e-mail).
    Desliga o opt-in sem precisar logar."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "unsubscribe"

    @extend_schema(
        request=inline_serializer("UnsubscribeRequest", {"token": serializers.CharField()}),
        responses=inline_serializer("UnsubscribeResponse", {"unsubscribed": serializers.BooleanField()}),
    )
    def post(self, request):
        token = request.data.get("token")
        if not isinstance(token, str) or not services.unsubscribe(token):
            return Response({"detail": "Link de descadastro inválido."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"unsubscribed": True})


# ---------------------------------------------------------------------------
# Infra do fim de semana
# ---------------------------------------------------------------------------
class InfraSuggestionView(APIView):
    """GET /api/promotions/infra-suggestion/ — projeção de carga do próximo
    fim de semana x capacidade local. Decisão de operação da plataforma: só
    admin (números agregados da plataforma inteira)."""
    permission_classes = [IsAdminUser]

    @extend_schema(responses=inline_serializer("InfraSuggestion", {"level": serializers.CharField()}))
    def get(self, request):
        return Response(infra.suggestion())
