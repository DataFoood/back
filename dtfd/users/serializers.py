from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


def tokens_for(user):
    """Par access/refresh pro usuário (mesmo formato do login)."""
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)
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
        extra_kwargs = {"allow_info": {"write_only": True}}

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


class LoginSerializer(TokenObtainPairSerializer):
    """Login JWT que já devolve o usuário — o front não precisa de 2ª chamada."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserDetailSerializer(self.user).data
        return data


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
