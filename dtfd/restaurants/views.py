import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from utils.pagination import DefaultPagination

from .models import (
    BusinessHour,
    Restaurant,
    RestaurantFavorite,
    RestaurantImage,
    RestaurantItem,
    RestaurantReview,
    RestaurantView,
)
from .permissions import (
    IsAuthorOrAdmin,
    IsParentRestaurantOwnerOrAdmin,
    IsRestaurantOwnerOrAdmin,
)
from .serializers import (
    BusinessHourSerializer,
    RestaurantFavoriteSerializer,
    RestaurantImageSerializer,
    RestaurantItemSerializer,
    RestaurantReadSerializer,
    RestaurantReviewSerializer,
    RestaurantWriteSerializer,
)

MAX_ITEMS = 6


class RestaurantListCreateView(ListCreateAPIView):
    """GET /api/restaurants/ — publico
       POST /api/restaurants/ — autenticado, vira owner"""
    queryset = Restaurant.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = DefaultPagination

    def get_serializer_class(self):
        return RestaurantWriteSerializer if self.request.method == "POST" else RestaurantReadSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class RestaurantDetailView(RetrieveUpdateDestroyAPIView):
    """GET publico; PUT/PATCH/DELETE so owner ou admin. DELETE = soft."""
    queryset = Restaurant.objects.all()
    permission_classes = [IsRestaurantOwnerOrAdmin]

    def get_serializer_class(self):
        return RestaurantWriteSerializer if self.request.method in ("PUT", "PATCH") else RestaurantReadSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()  # uma vez só
        # view-tracking: usuario autenticado visualizou -> incrementa contador
        if request.user.is_authenticated:
            view, created = RestaurantView.objects.get_or_create(
                user=request.user, restaurant=instance
            )
            if not created:
                RestaurantView.objects.filter(pk=view.pk).update(count=F("count") + 1)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


# ---------------------------------------------------------------------------
# REVIEWS (nested)
# ---------------------------------------------------------------------------
class ReviewListCreateView(ListCreateAPIView):
    serializer_class = RestaurantReviewSerializer
    permission_classes = [IsAuthorOrAdmin]

    def get_queryset(self):
        return RestaurantReview.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_create(self, serializer):
        restaurant = get_object_or_404(Restaurant, pk=self.kwargs["restaurant_pk"])
        serializer.save(author=self.request.user, restaurant=restaurant)
        restaurant.recalc_rating()


class ReviewDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = RestaurantReviewSerializer
    permission_classes = [IsAuthorOrAdmin]

    def get_queryset(self):
        return RestaurantReview.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_update(self, serializer):
        review = serializer.save()
        review.restaurant.recalc_rating()

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])
        instance.restaurant.recalc_rating()


# ---------------------------------------------------------------------------
# IMAGES (nested)
# ---------------------------------------------------------------------------
class ImageListCreateView(ListCreateAPIView):
    serializer_class = RestaurantImageSerializer
    permission_classes = [IsParentRestaurantOwnerOrAdmin]

    def get_queryset(self):
        return RestaurantImage.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_create(self, serializer):
        restaurant = get_object_or_404(Restaurant, pk=self.kwargs["restaurant_pk"])
        serializer.save(restaurant=restaurant)


class ImageDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = RestaurantImageSerializer
    permission_classes = [IsParentRestaurantOwnerOrAdmin]

    def get_queryset(self):
        return RestaurantImage.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


# ---------------------------------------------------------------------------
# BUSINESS HOURS (nested)
# ---------------------------------------------------------------------------
class BusinessHourListCreateView(ListCreateAPIView):
    serializer_class = BusinessHourSerializer
    permission_classes = [IsParentRestaurantOwnerOrAdmin]

    def get_queryset(self):
        return BusinessHour.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_create(self, serializer):
        restaurant = get_object_or_404(Restaurant, pk=self.kwargs["restaurant_pk"])
        day = serializer.validated_data["day_week"]
        if BusinessHour.objects.filter(restaurant=restaurant, day_week=day).exists():
            raise ValidationError({"day_week": "Já existe horário para este dia."})
        serializer.save(restaurant=restaurant)


class BusinessHourDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = BusinessHourSerializer
    permission_classes = [IsParentRestaurantOwnerOrAdmin]

    def get_queryset(self):
        return BusinessHour.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


# ---------------------------------------------------------------------------
# ITEMS (nested) — pratos principais, gestao do owner, limite de 6
# ---------------------------------------------------------------------------
class ItemListCreateView(ListCreateAPIView):
    serializer_class = RestaurantItemSerializer
    permission_classes = [IsParentRestaurantOwnerOrAdmin]

    def get_queryset(self):
        return RestaurantItem.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_create(self, serializer):
        # lock no restaurante serializa criações concorrentes -> sem TOCTOU
        with transaction.atomic():
            restaurant = get_object_or_404(
                Restaurant.objects.select_for_update(), pk=self.kwargs["restaurant_pk"]
            )
            if RestaurantItem.objects.filter(restaurant=restaurant).count() >= MAX_ITEMS:
                raise ValidationError(f"Máximo de {MAX_ITEMS} itens por restaurante.")
            serializer.save(restaurant=restaurant)


class ItemDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = RestaurantItemSerializer
    permission_classes = [IsParentRestaurantOwnerOrAdmin]

    def get_queryset(self):
        return RestaurantItem.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


# ---------------------------------------------------------------------------
# FAVORITES — sinal forte de preferencia
# ---------------------------------------------------------------------------
class FavoriteToggleView(APIView):
    """POST /api/restaurants/<pk>/favorite/   — favorita (idempotente)
       DELETE /api/restaurants/<pk>/favorite/ — desfavorita"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "FavoriteToggleResponse", {"favorited": serializers.BooleanField()}
        ),
    )
    def post(self, request, pk):
        restaurant = get_object_or_404(Restaurant, pk=pk)
        _, created = RestaurantFavorite.objects.get_or_create(
            user=request.user, restaurant=restaurant
        )
        return Response(
            {"favorited": True},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, pk):
        deleted, _ = RestaurantFavorite.objects.filter(
            user=request.user, restaurant_id=pk
        ).delete()
        if not deleted:
            return Response({"detail": "Não favoritado."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FavoriteListView(ListAPIView):
    """GET /api/restaurants/favorites/ — favoritos do usuário logado."""
    serializer_class = RestaurantFavoriteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return RestaurantFavorite.objects.filter(user=self.request.user)


# ---------------------------------------------------------------------------
# SEARCH — ponte pro shinzou (busca semântica)
# ---------------------------------------------------------------------------
class SearchView(APIView):
    """POST /api/search/ — repassa a query pro shinzou com service token +
    o JWT do usuário. Frontend fala só com o Django; shinzou fica interno.
    Só JWT (não sessão) — o Bearer precisa existir pra repassar ao shinzou."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    # quantas buscas manter por usuário (retenção)
    HISTORY_KEEP = 50

    @extend_schema(
        request=inline_serializer(
            "SearchRequest",
            {
                "query": serializers.CharField(),
                "limit": serializers.IntegerField(required=False),
            },
        ),
        responses=inline_serializer(
            "SearchResultItem",
            {
                "id": serializers.IntegerField(),
                "name": serializers.CharField(),
                "slug": serializers.CharField(),
                "score": serializers.FloatField(),
            },
            many=True,
        ),
        description="Repassa a busca semântica ao shinzou. Resposta = lista "
        "rankeada de restaurantes (campos exatos definidos pelo shinzou).",
    )
    def post(self, request):
        query = (request.data.get("query") or "").strip()
        if not query:
            return Response({"query": "Campo obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        payload = {"query": query, "limit": request.data.get("limit")}
        headers = {
            "X-Service-Token": settings.SHINZOU_SERVICE_TOKEN,
            "Authorization": request.headers.get("Authorization", ""),
        }
        try:
            resp = httpx.post(
                f"{settings.SHINZOU_URL}/search", json=payload, headers=headers, timeout=60
            )
        except httpx.RequestError:
            return Response(
                {"detail": "Serviço de busca indisponível."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # loga só com 200 E consentimento LGPD (allow_info). Poda além de N.
        if resp.status_code == status.HTTP_200_OK and request.user.allow_info:
            self._log_search(request.user, query)

        return Response(resp.json(), status=resp.status_code)

    def _log_search(self, user, query):
        from preferences.models import SearchHistory

        SearchHistory.objects.create(user=user, query=query)
        keep_ids = SearchHistory.objects.filter(user=user).values_list(
            "id", flat=True
        )[: self.HISTORY_KEEP]
        SearchHistory.objects.filter(user=user).exclude(id__in=list(keep_ids)).delete()
