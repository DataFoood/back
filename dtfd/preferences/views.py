from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from embeddings.search import DEFAULT_WEIGHTS

from .models import (
    BaseAffinity,
    RankingWeight,
    SearchHistory,
    UserAmbientAffinity,
    UserCuisineAffinity,
    UserPriceAffinity,
)
from .serializers import (
    AmbientAffinitySerializer,
    CuisineAffinitySerializer,
    PriceAffinitySerializer,
    SearchHistorySerializer,
)


class PreferencesView(APIView):
    """GET /api/preferences/ — afinidades do usuário logado (3 dimensões)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=inline_serializer(
            "PreferencesResponse",
            {
                "cuisines": CuisineAffinitySerializer(many=True),
                "ambients": AmbientAffinitySerializer(many=True),
                "price_ranges": PriceAffinitySerializer(many=True),
            },
        )
    )
    def get(self, request):
        user = request.user
        return Response({
            "cuisines": CuisineAffinitySerializer(
                UserCuisineAffinity.objects.filter(user=user), many=True
            ).data,
            "ambients": AmbientAffinitySerializer(
                UserAmbientAffinity.objects.filter(user=user), many=True
            ).data,
            "price_ranges": PriceAffinitySerializer(
                UserPriceAffinity.objects.filter(user=user), many=True
            ).data,
        })


class _AffinityEditView(RetrieveUpdateAPIView):
    """Base: edita o score de uma afinidade própria. Editar => is_manual=True
    (o recompute para de sobrescrever essa linha)."""
    permission_classes = [IsAuthenticated]
    model: type[BaseAffinity]

    def get_queryset(self):
        return self.model.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(is_manual=True)


class SearchHistoryView(ListAPIView):
    """GET /api/preferences/searches/ — buscas recentes do usuário logado."""
    serializer_class = SearchHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SearchHistory.objects.filter(user=self.request.user)[:50]


WEIGHTS_SCHEMA = inline_serializer(
    "RankingWeights", {key: serializers.FloatField(required=False) for key in DEFAULT_WEIGHTS}
)


class RankingWeightView(APIView):
    """GET/PATCH /api/preferences/weights/ — pesos do ranking da busca (admin).
    PATCH parcial: {"semantic": 1.0, "distance": 0.8, ...}."""
    permission_classes = [IsAdminUser]
    MAX_WEIGHT = 5.0

    def _current(self):
        return {**DEFAULT_WEIGHTS, **dict(RankingWeight.objects.values_list("key", "weight"))}

    @extend_schema(responses=WEIGHTS_SCHEMA)
    def get(self, request):
        return Response(self._current())

    @extend_schema(request=WEIGHTS_SCHEMA, responses=WEIGHTS_SCHEMA)
    def patch(self, request):
        current = self._current()
        if not isinstance(request.data, dict) or not request.data:
            return Response({"detail": "Envie {chave: peso}."}, status=status.HTTP_400_BAD_REQUEST)
        errors = {}
        for key, value in request.data.items():
            if key not in current:
                errors[key] = "Chave desconhecida."
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= self.MAX_WEIGHT:
                errors[key] = f"Número entre 0 e {self.MAX_WEIGHT}."
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        for key, value in request.data.items():
            RankingWeight.objects.update_or_create(key=key, defaults={"weight": float(value)})
        return Response(self._current())


class CuisineAffinityEditView(_AffinityEditView):
    model = UserCuisineAffinity
    serializer_class = CuisineAffinitySerializer


class AmbientAffinityEditView(_AffinityEditView):
    model = UserAmbientAffinity
    serializer_class = AmbientAffinitySerializer


class PriceAffinityEditView(_AffinityEditView):
    model = UserPriceAffinity
    serializer_class = PriceAffinitySerializer
