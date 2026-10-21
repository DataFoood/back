from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import (
    CreateAPIView,
    DestroyAPIView,
    ListAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


from .authentication import clear_auth_cookies, is_browser, to_cookie_session
from .models import User
from .permissions import IsOwnerOrAdmin
from .serializers import (
    LoginSerializer,
    RefreshSerializer,
    UserChangePasswordSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserPublicSerializer,
    UserUpdateSerializer,
    revoke_refresh_tokens,
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
    Navegador (X-Requested-With): grava a sessão em cookies HttpOnly e
    responde {user, access_expires_in}. API: {access, refresh, user}."""
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(responses=AuthResponse)
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if is_browser(request) and response.status_code == status.HTTP_200_OK:
            to_cookie_session(response)
        return response


class RefreshView(TokenRefreshView):
    """POST /api/users/login/refresh/ — rotaciona o refresh; conta
    removida/inativa -> 401. Navegador: sem corpo, lê o refresh do cookie e
    devolve os novos em cookie (tokens nunca no corpo — um XSS que chame o
    refresh não leva nada). API: {refresh} -> {access, refresh}."""
    serializer_class = RefreshSerializer

    def post(self, request, *args, **kwargs):
        cookie_mode = is_browser(request) and not request.data.get("refresh")
        if not cookie_mode:
            return super().post(request, *args, **kwargs)
        raw = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if not raw:
            return clear_auth_cookies(Response({"detail": "Sem sessão."}, status=status.HTTP_401_UNAUTHORIZED))
        serializer = self.get_serializer(data={"refresh": raw})
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, InvalidToken, AuthenticationFailed):
            # refresh revogado/expirado: apaga os cookies junto com o 401
            return clear_auth_cookies(Response({"detail": "Sessão expirada."}, status=status.HTTP_401_UNAUTHORIZED))
        return to_cookie_session(Response(dict(serializer.validated_data)))


class LogoutView(APIView):
    """POST /api/users/logout/ — invalida o refresh token (blacklist).
    O access expira sozinho (vida curta)."""
    permission_classes = [AllowAny]

    @extend_schema(
        request=inline_serializer("LogoutRequest", {"refresh": serializers.CharField()}),
        responses={204: None},
    )
    def post(self, request):
        token = request.data.get("refresh") or request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if not token:
            if is_browser(request):  # sem sessão: só garante os cookies limpos
                return clear_auth_cookies(Response(status=status.HTTP_204_NO_CONTENT))
            return Response({"refresh": "Campo obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            pass  # já inválido/expirado: logout é idempotente
        return clear_auth_cookies(Response(status=status.HTTP_204_NO_CONTENT))


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
        response = Response(
            {**tokens_for(user), "user": UserDetailSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )
        return to_cookie_session(response) if is_browser(request) else response


class UserListView(ListAPIView):
    """GET /users/ — listagem só para admin"""
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [IsAdminUser]


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

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        # encerrou a própria conta: apaga a sessão deste navegador também
        return clear_auth_cookies(response) if instance.pk == request.user.pk else response

    def perform_destroy(self, instance):
        from chats.models import ChatConversation

        instance.deleted_at = timezone.now()
        instance.is_active = False  # bloqueia login imediatamente
        instance.save(update_fields=["deleted_at", "is_active"])
        # derruba as sessões abertas em outros dispositivos
        revoke_refresh_tokens(instance)
        # conversas da busca pertencem à conta: saem junto com ela
        ChatConversation.objects.filter(user=instance).delete()


class UserRemovedListView(ListAPIView):
    """GET /api/users/removed/ — lista soft-deleted, só admin"""
    serializer_class = UserDetailSerializer
    permission_classes = [IsAdminUser]

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
    """POST /users/<pk>/change-password/ — só o próprio usuário.
    Trocar a senha encerra todas as sessões (refresh tokens antigos vão pra
    blacklist) e devolve um par novo pra sessão atual continuar."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=UserChangePasswordSerializer,
        responses=inline_serializer(
            "ChangePasswordResponse",
            {
                "detail": serializers.CharField(),
                "access": serializers.CharField(),
                "refresh": serializers.CharField(),
            },
        ),
    )
    def post(self, request, pk):
        if request.user.pk != pk:
            return Response({"detail": "Proibido."}, status=status.HTTP_403_FORBIDDEN)

        serializer = UserChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        revoke_refresh_tokens(user)
        response = Response({"detail": "Senha alterada com sucesso.", **tokens_for(user)})
        # sessão atual continua: navegador recebe o par novo em cookie
        return to_cookie_session(response) if is_browser(request) else response
