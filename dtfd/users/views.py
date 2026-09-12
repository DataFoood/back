from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import (
    CreateAPIView,
    DestroyAPIView,
    ListAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from utils.pagination import DefaultPagination

from .models import User
from .permissions import IsOwnerOrAdmin
from .serializers import (
    UserChangePasswordSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserUpdateSerializer,
)


class LoginView(TokenObtainPairView):
    """POST /api/users/login/ — JWT com rate limit (anti brute-force)."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class UserCreateView(CreateAPIView):
    """POST /api/users/register/ — cadastro aberto, com rate limit."""
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"


class UserListView(ListAPIView):
    """GET /users/ — listagem só para admin"""
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination


class UserDetailView(RetrieveUpdateAPIView):
    """GET /users/<pk>/ — qualquer autenticado
       PATCH /users/<pk>/ — só dono ou admin"""
    queryset = User.objects.all()
    permission_classes = [IsOwnerOrAdmin]

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return UserUpdateSerializer
        return UserDetailSerializer


class UserDeleteView(DestroyAPIView):
    """DELETE /api/users/<pk>/delete/ — soft delete, dono ou admin"""
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [IsOwnerOrAdmin]

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.is_active = False  # bloqueia login imediatamente
        instance.save(update_fields=["deleted_at", "is_active"])


class UserRemovedListView(ListAPIView):
    """GET /api/users/removed/ — lista soft-deleted, só admin"""
    serializer_class = UserDetailSerializer
    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination

    def get_queryset(self):
        return User.all_objects.filter(deleted_at__isnull=False)


class UserConsentView(APIView):
    """PATCH /api/users/consent/ — o próprio usuário liga/desliga o consentimento
    LGPD (allow_info). Sempre opera sobre request.user, nunca sobre terceiros."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            "ConsentRequest", {"allow_info": serializers.BooleanField()}
        ),
        responses=inline_serializer(
            "ConsentResponse", {"allow_info": serializers.BooleanField()}
        ),
    )
    def patch(self, request):
        value = request.data.get("allow_info")
        if not isinstance(value, bool):
            return Response(
                {"allow_info": "Campo obrigatório, booleano (true/false)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.allow_info = value
        request.user.save(update_fields=["allow_info"])
        return Response({"allow_info": value})


class UserChangePasswordView(APIView):
    """POST /users/<pk>/change-password/ — só o próprio usuário"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=UserChangePasswordSerializer,
        responses=inline_serializer(
            "ChangePasswordResponse", {"detail": serializers.CharField()}
        ),
    )
    def post(self, request, pk):
        if request.user.pk != pk:
            return Response({"detail": "Proibido."}, status=status.HTTP_403_FORBIDDEN)

        serializer = UserChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Senha alterada com sucesso."})
