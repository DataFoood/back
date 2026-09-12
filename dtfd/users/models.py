from django.contrib.auth.models import AbstractUser
from django.db import models

from utils import AbstractAudit

from .managers import UserManager


# AbstractUser fornece: first_name, last_name, password, is_staff, is_active,
#   is_superuser, last_login, date_joined, groups (M2M), user_permissions (M2M).
#   username é removido (login por email). first_name/last_name ficam inertes —
#   usamos o campo `name`.
# AbstractAudit fornece: created_at, updated_at, deleted_at.
class User(AbstractUser, AbstractAudit):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Cliente"
        OWNER = "owner", "Dono de restaurante"
        ADMIN = "admin", "Administrador"

    class Gender(models.TextChoices):
        MALE = "M", "Masculino"
        FEMALE = "F", "Feminino"
        OTHER = "O", "Outro"
        UNDISCLOSED = "N", "Não informado"

    username = None  # login por email

    name = models.CharField(max_length=150)
    cpf = models.CharField(max_length=11, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    birthday = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    avatar_url = models.URLField(blank=True)
    banner_url = models.URLField(blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    level = models.PositiveSmallIntegerField(default=1)
    # LGPD: só guarda histórico de busca/sinais se o usuário consentir.
    allow_info = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    # Anota com o nosso UserManager pra o checker usar a assinatura custom
    # (create_user/create_superuser por email). O ignore cobre o override do
    # objects herdado de AbstractUser (UserManager[Self] do Django).
    objects: UserManager = UserManager()  # type: ignore[assignment]
    all_objects = models.Manager()

    class Meta(AbstractUser.Meta):
        ordering = ["id"]  # paginação determinística

    def __str__(self):
        return f"{self.name} <{self.email}>"
