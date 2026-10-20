from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


def tokens_for(user):
    """Par access/refresh pro usuário (mesmo formato do login)."""
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def revoke_refresh_tokens(user):
    """Blacklista todos os refresh tokens emitidos pro usuário (encerra as
    sessões em todos os dispositivos). Access tokens já emitidos expiram
    sozinhos (vida curta)."""
    outstanding = OutstandingToken.objects.filter(user=user).exclude(
        blacklistedtoken__isnull=False
    )
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in outstanding],
        ignore_conflicts=True,
    )


# Unicidade contra TODAS as contas: o manager padrão esconde as encerradas
# (soft delete), mas o e-mail delas continua no banco -> sem isso o
# cadastro passava na validação e estourava IntegrityError (500).
# iexact: "Ana@x.com" e "ana@x.com" não viram duas contas.
UNIQUE_EMAIL = UniqueValidator(
    queryset=User.all_objects.all(), lookup="iexact",
    message="Já existe uma conta com este e-mail.",
)


def is_valid_cpf(digits: str) -> bool:
    """Dígitos verificadores do CPF (mesma regra do front, lib/format.ts)."""
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d) * (size + 1 - i) for i, d in enumerate(digits[:size]))
        if (total * 10) % 11 % 10 != int(digits[size]):
            return False
    return True


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)
    # aceita com máscara (000.000.000-00); validate_cpf normaliza p/ 11 dígitos
    cpf = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=14)
    # Tipo de conta escolhido no cadastro. Só customer/owner — admin nunca
    # nasce pelo register. `role` em si continua ignorado (anti mass-assignment).
    account_type = serializers.ChoiceField(
        choices=[User.Role.CUSTOMER, User.Role.OWNER],
        default=User.Role.CUSTOMER,
        write_only=True,
    )

    class Meta:
        model = User
        fields = ["id", "name", "email", "cpf", "phone", "password",
                  "confirm_password", "account_type", "allow_info"]
        extra_kwargs = {
            "allow_info": {"write_only": True},
            "email": {"validators": [UNIQUE_EMAIL]},
        }

    def validate_cpf(self, value):
        # "" viraria um segundo CPF vazio na coluna unique -> trata como ausente
        digits = "".join(ch for ch in (value or "") if ch.isdigit())
        if not digits:
            return None
        if not is_valid_cpf(digits):
            raise serializers.ValidationError("CPF inválido.")
        if User.all_objects.filter(cpf=digits).exists():
            raise serializers.ValidationError("Já existe uma conta com este CPF.")
        return digits

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Senhas não coincidem."})
        return attrs

    def create(self, validated_data):
        validated_data["role"] = validated_data.pop("account_type")
        return User.objects.create_user(**validated_data)


class UserDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "name", "email", "cpf", "phone", "birthday", "gender",
                  "avatar_url", "banner_url", "role", "level", "allow_info",
                  "is_active", "created_at"]
        read_only_fields = ["id", "role", "level", "is_active", "created_at"]


class UserPublicSerializer(serializers.ModelSerializer):
    """O que um usuário pode ver de OUTRO usuário — sem dado pessoal (LGPD)."""

    class Meta:
        model = User
        fields = ["id", "name", "avatar_url", "banner_url", "created_at"]
        read_only_fields = fields


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["name", "email", "phone", "birthday", "gender", "avatar_url",
                  "banner_url", "allow_info"]
        extra_kwargs = {"email": {"validators": [UNIQUE_EMAIL]}}


class LoginSerializer(TokenObtainPairSerializer):
    """Login JWT que já devolve o usuário — o front não precisa de 2ª chamada."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserDetailSerializer(self.user).data
        return data


class RefreshSerializer(TokenRefreshSerializer):
    """Refresh que trata conta removida como credencial inválida (401).
    O serializer do simplejwt usa User.objects.get(): como o manager filtra
    soft-deleted, a conta removida estourava DoesNotExist -> 500."""

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except User.DoesNotExist:
            raise AuthenticationFailed(
                "Conta inexistente ou removida.", code="no_active_account"
            )


class UserChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Senha atual incorreta.")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs.pop("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Senhas não coincidem."})
        return attrs

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
