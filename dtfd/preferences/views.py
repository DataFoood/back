from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    BaseAffinity,
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
from .tasks import recompute_all, recompute_one


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


class RecomputeView(APIView):
    """POST /api/preferences/recompute/ — enfileira recálculo (admin, async).
    body: {"user_id": int}  (omitido: todos)"""
    permission_classes = [IsAdminUser]

    @extend_schema(
        request=inline_serializer(
            "RecomputeRequest",
            {"user_id": serializers.IntegerField(required=False)},
        ),
        responses=inline_serializer(
            "RecomputeResponse",
            {"task_id": serializers.CharField(), "status": serializers.CharField()},
        ),
    )
    def post(self, request):
        user_id = request.data.get("user_id")
        if user_id:
            task = recompute_one.delay(int(user_id))
        else:
            task = recompute_all.delay()
        return Response(
            {"task_id": task.id, "status": "enfileirado"},
            status=status.HTTP_202_ACCEPTED,
        )


class CuisineAffinityEditView(_AffinityEditView):
    model = UserCuisineAffinity
    serializer_class = CuisineAffinitySerializer


class AmbientAffinityEditView(_AffinityEditView):
    model = UserAmbientAffinity
    serializer_class = AmbientAffinitySerializer


class PriceAffinityEditView(_AffinityEditView):
    model = UserPriceAffinity
    serializer_class = PriceAffinitySerializer
