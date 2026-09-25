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
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from utils.pagination import DefaultPagination

from .models import User
from .permissions import IsOwnerOrAdmin
from .serializers import (
    LoginSerializer,
    UserChangePasswordSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserPublicSerializer,
    UserUpdateSerializer,
    tokens_for,
)

AuthResponse = inline_serializer(
    "AuthResponse",
    {
        "access": serializers.CharField(),
        "refresh": serializers.CharField(),
        "user": UserDetailSerializer(),
    },
)


class LoginView(TokenObtainPairView):
    """POST /api/users/login/ — JWT com rate limit (anti brute-force).
    Retorna {access, refresh, user}."""
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(responses=AuthResponse)
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    """POST /api/users/logout/ — invalida o refresh token (blacklist).
    O access expira sozinho (vida curta)."""
    permission_classes = [AllowAny]

    @extend_schema(
        request=inline_serializer("LogoutRequest", {"refresh": serializers.CharField()}),
        responses={204: None},
    )
    def post(self, request):
        token = request.data.get("refresh")
        if not token:
            return Response({"refresh": "Campo obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            pass  # já inválido/expirado: logout é idempotente
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(RetrieveUpdateAPIView):
    """GET/PATCH /api/users/me/ — perfil do usuário logado."""
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "options"]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return UserUpdateSerializer
        return UserDetailSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(UserDetailSerializer(self.get_object()).data)


class UserCreateView(CreateAPIView):
    """POST /api/users/register/ — cadastro aberto, com rate limit."""
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    @extend_schema(responses={201: AuthResponse})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # já autentica: o front entra direto após o cadastro
        return Response(
            {**tokens_for(user), "user": UserDetailSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class UserListView(ListAPIView):
    """GET /users/ — listagem só para admin"""
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination


class UserDetailView(RetrieveUpdateAPIView):
    """GET /users/<pk>/ — qualquer autenticado (perfil completo só p/ dono
       ou admin; demais veem o perfil público, sem dado pessoal)
       PATCH /users/<pk>/ — só dono ou admin"""
    queryset = User.objects.all()
    permission_classes = [IsOwnerOrAdmin]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance == request.user or request.user.is_staff:
            return Response(UserDetailSerializer(instance).data)
        return Response(UserPublicSerializer(instance).data)

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
