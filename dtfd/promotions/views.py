from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.generics import DestroyAPIView, ListCreateAPIView

from restaurants.models import Restaurant
from restaurants.permissions import IsParentRestaurantOwnerOrAdmin

from .models import FlashPromotion
from .serializers import FlashPromotionSerializer


class _RestaurantScoped:
    permission_classes = [IsParentRestaurantOwnerOrAdmin]

    def restaurant(self):
        return get_object_or_404(Restaurant, pk=self.kwargs["restaurant_pk"])


class PromotionListCreateView(_RestaurantScoped, ListCreateAPIView):
    """GET/POST /api/restaurants/<id>/promotions/ — leitura pública, criação do dono.
    Lista as ativas e agendadas + as 20 últimas encerradas."""
    serializer_class = FlashPromotionSerializer

    def get_queryset(self):
        return FlashPromotion.objects.filter(restaurant_id=self.kwargs["restaurant_pk"]).prefetch_related("items__item")[:30]

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "restaurant": self.restaurant()}


class PromotionEndView(_RestaurantScoped, DestroyAPIView):
    """DELETE /api/restaurants/<id>/promotions/<pk>/ — encerra agora (mantém o histórico)."""
    serializer_class = FlashPromotionSerializer

    def get_queryset(self):
        return FlashPromotion.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_destroy(self, instance):
        now = timezone.now()
        if instance.ends_at > now:
            instance.ends_at = max(now, instance.starts_at)
            instance.save(update_fields=["ends_at"])
