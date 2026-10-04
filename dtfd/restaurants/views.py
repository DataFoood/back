import logging
from datetime import timedelta
from typing import cast

import httpx
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
    IsAdminUser,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from analytics.models import RegionVisit, RestaurantDailyStat
from analytics.services import bump_platform, bump_restaurants, record_region_visit
from embeddings.search import haversine_km, search
from embeddings.tasks import reindex_one
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
    primary_address,
    RestaurantCardSerializer,
    RestaurantFavoriteSerializer,
    RestaurantImageSerializer,
    RestaurantItemSerializer,
    RestaurantAdminSerializer,
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
         ?lat=&lon= (visitante; não é guardado) + ?ordering=distance e/ou ?radius_km=
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
        qs = qs.distinct().order_by(*ordering).prefetch_related(*CARD_PREFETCH)

        origin = _visitor_coords(params)
        if origin is None:
            return qs
        return self._by_distance(qs, origin, params)

    @staticmethod
    def _by_distance(qs, origin, params):
        """Anota distance_km; ordena por distância e/ou corta no raio.
        ponytail: distância calculada em Python sobre o filtro inteiro; PostGIS
        (ou bounding box no SQL) se o catálogo passar de alguns milhares."""
        rows = list(qs)
        for r in rows:
            address = primary_address(r)
            has_coords = address is not None and address.latitude is not None
            r.distance_km = (
                round(haversine_km(*origin, float(address.latitude), float(address.longitude)), 1)
                if has_coords else None
            )
        try:
            radius = float(params["radius_km"])
        except (KeyError, ValueError):
            radius = None
        if radius is not None:
            rows = [r for r in rows if r.distance_km is not None and r.distance_km <= radius]
        if params.get("ordering") == "distance":
            rows.sort(key=lambda r: (r.distance_km is None, r.distance_km or 0))
        return rows

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


def _visitor_coords(params):
    """(lat, lon) do visitante vindo da query (?lat=&lon=), ou None se ausente/inválido."""
    try:
        lat, lon = float(params["lat"]), float(params["lon"])
    except (KeyError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


class RestaurantDetailView(RetrieveUpdateDestroyAPIView):
    """GET publico; PUT/PATCH/DELETE so owner ou admin. DELETE = soft.
    Também atende GET /api/restaurants/by-slug/<slug>/.
    Métricas do dono (anônimas): ?src=search conta clique vindo da busca;
    ?lat=&lon= (coordenada do visitante) conta a visita na região (~1 km)."""
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
            bump_restaurants([instance.pk], "views")
            if request.query_params.get("src") == "search":
                bump_restaurants([instance.pk], "search_clicks")
            coords = _visitor_coords(request.query_params)
            if coords:
                record_region_visit(instance.pk, *coords)
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
        instance.soft_delete()


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
                "views_window": serializers.IntegerField(),
                "search_impressions_window": serializers.IntegerField(),
                "search_clicks_window": serializers.IntegerField(),
                "search_ctr": serializers.FloatField(allow_null=True),
                "series": serializers.ListField(child=serializers.DictField()),
                "regions": inline_serializer(
                    "RegionVisits",
                    {
                        "label": serializers.CharField(),
                        "lat": serializers.FloatField(),
                        "lon": serializers.FloatField(),
                        "visits": serializers.IntegerField(),
                    },
                    many=True,
                ),
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
        traffic = {
            row["date"]: row
            for row in RestaurantDailyStat.objects.filter(restaurant=restaurant, date__gte=since)
            .values("date", "views", "search_impressions", "search_clicks")
        }
        empty = {"views": 0, "search_impressions": 0, "search_clicks": 0}
        series = []
        for i in range(self.WINDOW_DAYS):
            day = since + timedelta(days=i)
            t = traffic.get(day, empty)
            series.append({
                "date": day.isoformat(),
                "favorites": fav_daily.get(day, 0),
                "reviews": rev_daily.get(day, 0),
                "views": t["views"],
                "search_impressions": t["search_impressions"],
                "search_clicks": t["search_clicks"],
            })
        impressions = sum(row["search_impressions"] for row in series)
        clicks = sum(row["search_clicks"] for row in series)
        regions = (
            RegionVisit.objects.filter(restaurant=restaurant, date__gte=since)
            .values("cell__label", "cell__lat", "cell__lon")
            .annotate(visits=Sum("count"))
            .order_by("-visits")[:10]
        )
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
            "views_window": sum(row["views"] for row in series),
            "search_impressions_window": impressions,
            "search_clicks_window": clicks,
            "search_ctr": round(clicks / impressions, 4) if impressions else None,
            "series": series,
            "regions": [
                {
                    "label": r["cell__label"] or f"{r['cell__lat']}, {r['cell__lon']}",
                    "lat": float(r["cell__lat"]),
                    "lon": float(r["cell__lon"]),
                    "visits": r["visits"],
                }
                for r in regions
            ],
            "recent_reviews": RestaurantReviewSerializer(
                reviews.select_related("author").order_by("-created_at")[:5], many=True
            ).data,
        })


# ---------------------------------------------------------------------------
# MODERAÇÃO (admin)
# ---------------------------------------------------------------------------
class RestaurantAdminListView(ListAPIView):
    """GET /api/restaurants/admin/ — todos, inclusive removidos (admin).
    ?q= (nome)  ?deleted=true|false"""
    serializer_class = RestaurantAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination

    def get_queryset(self):
        qs = Restaurant.all_objects.select_related("owner").prefetch_related("addresses")
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        deleted = self.request.query_params.get("deleted")
        if deleted in ("true", "false"):
            qs = qs.filter(deleted_at__isnull=deleted == "false")
        return qs.order_by("-created_at", "id")


class RestaurantRestoreView(APIView):
    """POST /api/restaurants/<pk>/restore/ — desfaz o soft delete (admin)."""
    permission_classes = [IsAdminUser]

    @extend_schema(request=None, responses=RestaurantAdminSerializer)
    def post(self, request, pk):
        restaurant = get_object_or_404(Restaurant.all_objects, pk=pk)
        restaurant.deleted_at = None
        restaurant.save(update_fields=["deleted_at"])
        return Response(RestaurantAdminSerializer(restaurant).data)


class RestaurantReindexView(APIView):
    """POST /api/restaurants/<pk>/reindex/ — regera o embedding agora (admin, async)."""
    permission_classes = [IsAdminUser]

    @extend_schema(request=None, responses={202: inline_serializer("ReindexQueued", {"task_id": serializers.CharField()})})
    def post(self, request, pk):
        get_object_or_404(Restaurant, pk=pk)
        task = reindex_one.delay(pk)
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)


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
        instance.soft_delete()
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
        instance.soft_delete()


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
        instance.soft_delete()


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
        instance.soft_delete()


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
# SEARCH — busca semântica (embeddings.search)
# ---------------------------------------------------------------------------
class SearchView(APIView):
    """POST /api/search/ — busca semântica por linguagem natural."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "search"

    # quantas buscas manter por usuário (retenção)
    HISTORY_KEEP = 50
    # entrada: query vira embedding (custo) -> tamanho limitado; limit 1..50
    MAX_QUERY_LENGTH = 500
    MAX_LIMIT = 50
    DEFAULT_LIMIT = 15
    MAX_RADIUS_KM = 100

    @extend_schema(
        request=inline_serializer(
            "SearchRequest",
            {
                "query": serializers.CharField(),
                "limit": serializers.IntegerField(required=False),
                "lat": serializers.FloatField(required=False),
                "lon": serializers.FloatField(required=False),
                "radius_km": serializers.FloatField(required=False),
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
                        "distance_km": serializers.FloatField(allow_null=True),
                    },
                    many=True,
                ),
            },
        ),
        description="Busca semântica. Resposta = lista rankeada de cards de "
        "restaurante + score do ranking + match (0-100, similaridade semântica). "
        "`lat`/`lon` opcionais (localização do usuário, usada só neste request) "
        "favorecem os mais próximos; `radius_km` corta quem está fora do raio.",
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

        origin, radius_km, geo_error = self._geo(request.data)
        if geo_error:
            return Response(geo_error, status=status.HTTP_400_BAD_REQUEST)

        try:
            ranked = search(request.user, query, limit or self.DEFAULT_LIMIT, origin, radius_km)
        except httpx.HTTPError:
            logger.warning("Ollama indisponível na busca", exc_info=True)
            bump_platform("search_failures")
            return Response(
                {"detail": "Serviço de busca indisponível."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        bump_platform("searches")

        # loga só com sucesso E consentimento LGPD (allow_info). Poda além de N.
        if request.user.allow_info:
            self._log_search(request.user, query)

        results = self._hydrate(request, ranked)
        # impressão = restaurante efetivamente exibido no resultado
        bump_restaurants([row["restaurant"]["id"] for row in results], "search_impressions")
        return Response({"results": results})

    def _geo(self, data):
        """(origin, radius_km, erro). Tudo opcional; lat e lon andam juntos."""
        def number(key):
            value = data.get(key)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError
            return float(value)

        try:
            lat, lon, radius = number("lat"), number("lon"), number("radius_km")
        except ValueError:
            return None, None, {"detail": "lat, lon e radius_km devem ser números."}
        if (lat is None) != (lon is None):
            return None, None, {"detail": "Envie lat e lon juntos."}
        if lat is None:
            if radius is not None:
                return None, None, {"radius_km": "Requer lat e lon."}
            return None, None, None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None, {"detail": "Coordenada fora do intervalo."}
        if radius is not None and not 0 < radius <= self.MAX_RADIUS_KM:
            return None, None, {"radius_km": f"Entre 0 e {self.MAX_RADIUS_KM} km."}
        return (lat, lon), radius, None

    @staticmethod
    def _hydrate(request, ranked):
        """Troca os ids do ranking pelos cards completos, mantendo a ordem."""
        restaurants = Restaurant.objects.filter(
            pk__in=[rid for rid, *_ in ranked]
        ).prefetch_related(*CARD_PREFETCH)
        by_id = {r.pk: r for r in restaurants}
        context = {"request": request, "favorited_ids": favorited_ids(request, restaurants)}
        return [
            {
                "restaurant": RestaurantCardSerializer(by_id[rid], context=context).data,
                "score": round(score, 4),
                "match": max(0, min(100, round(similarity * 100))),
                "distance_km": None if distance is None else round(distance, 1),
            }
            for rid, score, similarity, distance in ranked
            if rid in by_id
        ]

    def _log_search(self, user, query):
        from preferences.models import SearchHistory

        SearchHistory.objects.create(user=user, query=query)
        keep_ids = SearchHistory.objects.filter(user=user).values_list(
            "id", flat=True
        )[: self.HISTORY_KEEP]
        SearchHistory.objects.filter(user=user).exclude(id__in=list(keep_ids)).delete()
