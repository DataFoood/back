import logging
from datetime import timedelta
from typing import cast

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from users.models import User
from utils.pagination import DefaultPagination

from .models import (
    Ambient,
    BusinessHour,
    BusinessModel,
    Cuisine,
    PhysicalFormat,
    PriceRange,
    Restaurant,
    RestaurantFavorite,
    RestaurantImage,
    RestaurantItem,
    RestaurantReview,
    RestaurantView,
    ServiceModel,
    TargetAudience,
)
from .permissions import (
    IsAuthorOrAdmin,
    IsParentRestaurantOwnerOrAdmin,
    IsRestaurantOwnerOrAdmin,
)
from .serializers import (
    CARD_PREFETCH,
    BusinessHourSerializer,
    LookupSerializer,
    RestaurantCardSerializer,
    RestaurantFavoriteSerializer,
    RestaurantImageSerializer,
    RestaurantItemSerializer,
    RestaurantReadSerializer,
    RestaurantReviewSerializer,
    RestaurantWriteSerializer,
)

logger = logging.getLogger(__name__)

MAX_ITEMS = 6

DETAIL_PREFETCH = [
    *CARD_PREFETCH, "images", "items", "service_models", "target_audiences",
    "business_models", "physical_formats", "reviews__author",
]

# query param -> campo M2M (filtros por taxonomia; ids separados por vírgula)
TAXONOMY_FILTERS = {
    "cuisine": "cuisines",
    "ambient": "ambients",
    "price_range": "price_ranges",
    "service_model": "service_models",
    "target_audience": "target_audiences",
}

ORDERINGS = {
    "recent": ["-created_at", "id"],
    "rating": ["-average_rating", "-total_reviews", "id"],
    "name": ["name", "id"],
}


def _int_list(raw):
    return [int(v) for v in raw.split(",") if v.strip().isdigit()]


def favorited_ids(request, restaurants=None):
    """ids favoritados pelo usuário (1 query) -> is_favorited sem N+1."""
    if not request.user.is_authenticated:
        return set()
    qs = RestaurantFavorite.objects.filter(user=request.user)
    if restaurants is not None:
        qs = qs.filter(restaurant__in=restaurants)
    return set(qs.values_list("restaurant_id", flat=True))


class _CardListMixin:
    """Injeta favorited_ids no contexto dos cards da página atual."""

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)
        context = {**self.get_serializer_context(), "favorited_ids": favorited_ids(request, rows)}
        data = RestaurantCardSerializer(rows, many=True, context=context).data
        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)


class RestaurantListCreateView(_CardListMixin, ListCreateAPIView):
    """GET /api/restaurants/ — publico, paginado, com filtros:
         ?q=texto  ?cuisine=1,2  ?ambient=  ?price_range=  ?service_model=
         ?target_audience=  ?city=  ?delivery=true  ?ordering=recent|rating|name
       POST /api/restaurants/ — autenticado, vira owner"""
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = DefaultPagination

    def get_serializer_class(self):
        return RestaurantWriteSerializer if self.request.method == "POST" else RestaurantCardSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = Restaurant.objects.all()

        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        for param, field in TAXONOMY_FILTERS.items():
            ids = _int_list(params.get(param, ""))
            if ids:
                qs = qs.filter(**{f"{field}__in": ids})
        city = (params.get("city") or "").strip()
        if city:
            qs = qs.filter(
                addresses__city__iexact=city, addresses__deleted_at__isnull=True
            )
        if params.get("delivery") == "true":
            qs = qs.filter(has_delivery=True)

        ordering = ORDERINGS.get(params.get("ordering", ""), ORDERINGS["recent"])
        return qs.distinct().order_by(*ordering).prefetch_related(*CARD_PREFETCH)

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(owner=user)
        # quem cadastra restaurante vira dono (admin continua admin)
        if user.role == user.Role.CUSTOMER:
            user.role = user.Role.OWNER
            user.save(update_fields=["role"])


class MyRestaurantsView(_CardListMixin, ListAPIView):
    """GET /api/restaurants/mine/ — restaurantes do usuário logado (painel)."""
    permission_classes = [IsAuthenticated]
    serializer_class = RestaurantCardSerializer

    def get_queryset(self):
        return (
            Restaurant.objects.filter(owner=self.request.user)
            .order_by("-created_at", "id")
            .prefetch_related(*CARD_PREFETCH)
        )


class TaxonomiesView(APIView):
    """GET /api/restaurants/taxonomies/ — todas as taxonomias (filtros/forms)."""
    permission_classes = [AllowAny]

    MODELS = {
        "cuisines": Cuisine,
        "ambients": Ambient,
        "service_models": ServiceModel,
        "target_audiences": TargetAudience,
        "price_ranges": PriceRange,
        "business_models": BusinessModel,
        "physical_formats": PhysicalFormat,
    }

    @extend_schema(
        responses=inline_serializer(
            "TaxonomiesResponse",
            {key: LookupSerializer(many=True) for key in MODELS},
        )
    )
    def get(self, request):
        return Response({
            key: LookupSerializer(model.objects.order_by("id"), many=True).data
            for key, model in self.MODELS.items()
        })


class RestaurantDetailView(RetrieveUpdateDestroyAPIView):
    """GET publico; PUT/PATCH/DELETE so owner ou admin. DELETE = soft.
    Também atende GET /api/restaurants/by-slug/<slug>/."""
    queryset = Restaurant.objects.prefetch_related(*DETAIL_PREFETCH)
    permission_classes = [IsRestaurantOwnerOrAdmin]

    def get_serializer_class(self):
        return RestaurantWriteSerializer if self.request.method in ("PUT", "PATCH") else RestaurantReadSerializer

    def get_object(self):
        if "slug" in self.kwargs:
            self.lookup_field = "slug"
        return super().get_object()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()  # uma vez só
        # métrica agregada/anônima do dono: todo acesso conta, menos o do
        # próprio dono/admin (o painel recarrega o detalhe a cada edição)
        user = cast(User, request.user)
        is_manager = user.is_authenticated and (instance.owner_id == user.pk or user.is_staff)
        if not is_manager:
            Restaurant.objects.filter(pk=instance.pk).update(view_count=F("view_count") + 1)
        # sinal de preferência por usuário: só com consentimento LGPD
        if request.user.is_authenticated and request.user.allow_info:
            view, created = RestaurantView.objects.get_or_create(
                user=request.user, restaurant=instance
            )
            if not created:
                RestaurantView.objects.filter(pk=view.pk).update(count=F("count") + 1)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        # responde com a representação de leitura (o front re-renderiza direto)
        super().update(request, *args, **kwargs)
        instance = Restaurant.objects.prefetch_related(*DETAIL_PREFETCH).get(pk=self.get_object().pk)
        return Response(RestaurantReadSerializer(instance, context=self.get_serializer_context()).data)

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


class RestaurantStatsView(APIView):
    """GET /api/restaurants/<pk>/stats/ — métricas do restaurante (dono/admin).
    Tudo agregado: nenhum dado pessoal de quem visualizou/favoritou."""
    permission_classes = [IsAuthenticated]
    WINDOW_DAYS = 30

    @extend_schema(
        responses=inline_serializer(
            "RestaurantStats",
            {
                "view_count": serializers.IntegerField(),
                "favorites_total": serializers.IntegerField(),
                "favorites_window": serializers.IntegerField(),
                "reviews_total": serializers.IntegerField(),
                "reviews_window": serializers.IntegerField(),
                "average_rating": serializers.FloatField(),
                "rating_distribution": serializers.DictField(child=serializers.IntegerField()),
                "window_days": serializers.IntegerField(),
                "series": serializers.ListField(child=serializers.DictField()),
                "recent_reviews": RestaurantReviewSerializer(many=True),
            },
        )
    )
    def get(self, request, pk):
        restaurant = get_object_or_404(Restaurant, pk=pk)
        if restaurant.owner != request.user and not request.user.is_staff:
            return Response({"detail": "Proibido."}, status=status.HTTP_403_FORBIDDEN)

        today = timezone.localdate()
        since = today - timedelta(days=self.WINDOW_DAYS - 1)
        favorites = RestaurantFavorite.objects.filter(restaurant=restaurant)
        reviews = RestaurantReview.objects.filter(restaurant=restaurant)

        def daily(qs):
            rows = (
                qs.filter(created_at__date__gte=since)
                .annotate(day=TruncDate("created_at"))
                .values("day")
                .annotate(n=Count("id"))
            )
            return {row["day"]: row["n"] for row in rows}

        fav_daily, rev_daily = daily(favorites), daily(reviews)
        series = [
            {
                "date": (since + timedelta(days=i)).isoformat(),
                "favorites": fav_daily.get(since + timedelta(days=i), 0),
                "reviews": rev_daily.get(since + timedelta(days=i), 0),
            }
            for i in range(self.WINDOW_DAYS)
        ]
        distribution = {str(n): 0 for n in range(1, 6)}
        for row in reviews.values("rating").annotate(n=Count("id")):
            distribution[str(row["rating"])] = row["n"]

        return Response({
            "view_count": restaurant.view_count,
            "favorites_total": favorites.count(),
            "favorites_window": sum(fav_daily.values()),
            "reviews_total": restaurant.total_reviews,
            "reviews_window": sum(rev_daily.values()),
            "average_rating": float(restaurant.average_rating),
            "rating_distribution": distribution,
            "window_days": self.WINDOW_DAYS,
            "series": series,
            "recent_reviews": RestaurantReviewSerializer(
                reviews.select_related("author").order_by("-created_at")[:5], many=True
            ).data,
        })


# ---------------------------------------------------------------------------
# REVIEWS (nested)
# ---------------------------------------------------------------------------
class ReviewListCreateView(ListCreateAPIView):
    serializer_class = RestaurantReviewSerializer
    permission_classes = [IsAuthorOrAdmin]

    def get_queryset(self):
        return (
            RestaurantReview.objects.filter(restaurant_id=self.kwargs["restaurant_pk"])
            .select_related("author")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        restaurant = get_object_or_404(Restaurant, pk=self.kwargs["restaurant_pk"])
        user = self.request.user
        # integridade da nota média: dono não se avalia; 1 avaliação por pessoa
        if restaurant.owner_id == user.pk:
            raise ValidationError({"detail": "Donos não podem avaliar o próprio restaurante."})
        if RestaurantReview.objects.filter(restaurant=restaurant, author=user).exists():
            raise ValidationError({"detail": "Você já avaliou este restaurante."})
        serializer.save(author=user, restaurant=restaurant)
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
        # a UniqueConstraint (restaurant, day_week) inclui linhas soft-deleted:
        # recriar um dia removido reaproveita a linha em vez de dar IntegrityError
        removed = BusinessHour.all_objects.filter(
            restaurant=restaurant, day_week=day, deleted_at__isnull=False
        ).first()
        if removed is not None:
            serializer.instance = removed
            serializer.save(restaurant=restaurant, deleted_at=None)
            return
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
        return (
            RestaurantFavorite.objects.filter(
                user=self.request.user, restaurant__deleted_at__isnull=True
            )
            .select_related("restaurant")
            .prefetch_related(*[f"restaurant__{p}" for p in CARD_PREFETCH])
            .order_by("-created_at")
        )

    def get_serializer_context(self):
        # tudo aqui é favorito por definição
        context = super().get_serializer_context()
        context["favorited_ids"] = set(self.get_queryset().values_list("restaurant_id", flat=True))
        return context


# ---------------------------------------------------------------------------
# SEARCH — ponte pro shinzou (busca semântica)
# ---------------------------------------------------------------------------
class SearchView(APIView):
    """POST /api/search/ — repassa a query pro shinzou com service token +
    o JWT do usuário. Frontend fala só com o Django; shinzou fica interno.
    Só JWT (não sessão) — o Bearer precisa existir pra repassar ao shinzou."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "search"

    # quantas buscas manter por usuário (retenção)
    HISTORY_KEEP = 50
    # entrada: query vira embedding (custo) -> tamanho limitado; limit 1..50
    MAX_QUERY_LENGTH = 500
    MAX_LIMIT = 50

    @extend_schema(
        request=inline_serializer(
            "SearchRequest",
            {
                "query": serializers.CharField(),
                "limit": serializers.IntegerField(required=False),
            },
        ),
        responses=inline_serializer(
            "SearchResponse",
            {
                "results": inline_serializer(
                    "SearchResultItem",
                    {
                        "restaurant": RestaurantCardSerializer(),
                        "score": serializers.FloatField(),
                        "match": serializers.IntegerField(allow_null=True),
                    },
                    many=True,
                ),
            },
        ),
        description="Busca semântica (via shinzou). Resposta = lista rankeada "
        "de cards de restaurante + score do ranking + match (0-100, "
        "similaridade semântica).",
    )
    def post(self, request):
        query = request.data.get("query")
        if not isinstance(query, str) or not query.strip():
            return Response({"query": "Campo obrigatório (texto)."}, status=status.HTTP_400_BAD_REQUEST)
        query = query.strip()
        if len(query) > self.MAX_QUERY_LENGTH:
            return Response(
                {"query": f"Máximo de {self.MAX_QUERY_LENGTH} caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = request.data.get("limit")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_LIMIT
        ):
            return Response(
                {"limit": f"Inteiro entre 1 e {self.MAX_LIMIT}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {"query": query, "limit": limit}
        headers = {
            "X-Service-Token": settings.SHINZOU_SERVICE_TOKEN,
            "Authorization": request.headers.get("Authorization", ""),
        }
        try:
            resp = httpx.post(
                f"{settings.SHINZOU_URL}/search", json=payload, headers=headers, timeout=60
            )
        except httpx.RequestError:
            logger.warning("shinzou inacessível", exc_info=True)
            return self._unavailable()

        if resp.status_code != status.HTTP_200_OK:
            logger.warning("shinzou respondeu %s", resp.status_code)
            return self._unavailable()
        try:
            raw_results = resp.json().get("results", [])
        except ValueError:
            return self._unavailable()

        # loga só com 200 E consentimento LGPD (allow_info). Poda além de N.
        if request.user.allow_info:
            self._log_search(request.user, query)

        return Response({"results": self._hydrate(request, raw_results)})

    @staticmethod
    def _unavailable():
        return Response(
            {"detail": "Serviço de busca indisponível."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _hydrate(request, raw_results):
        """Troca o restaurante mínimo do shinzou pelo card completo, mantendo
        a ordem do ranking. Restaurante sumido (soft-deleted) é descartado."""
        ids = [
            (row.get("restaurant") or {}).get("id") for row in raw_results
        ]
        restaurants = Restaurant.objects.filter(pk__in=[i for i in ids if i]).prefetch_related(*CARD_PREFETCH)
        by_id = {r.pk: r for r in restaurants}
        context = {"request": request, "favorited_ids": favorited_ids(request, restaurants)}

        results = []
        for row, rid in zip(raw_results, ids):
            restaurant = by_id.get(rid)
            if restaurant is None:
                continue
            similarity = row.get("similarity")
            match = None
            if isinstance(similarity, (int, float)):
                match = max(0, min(100, round(similarity * 100)))
            results.append({
                "restaurant": RestaurantCardSerializer(restaurant, context=context).data,
                "score": row.get("score"),
                "match": match,
            })
        return results

    def _log_search(self, user, query):
        from preferences.models import SearchHistory

        SearchHistory.objects.create(user=user, query=query)
        keep_ids = SearchHistory.objects.filter(user=user).values_list(
            "id", flat=True
        )[: self.HISTORY_KEEP]
        SearchHistory.objects.filter(user=user).exclude(id__in=list(keep_ids)).delete()
