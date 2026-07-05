from typing import cast

from rest_framework.permissions import BasePermission

from restaurants.models import Restaurant
from users.models import User


def owns_entity(user: User, entity) -> bool:
    """True se `user` pode gerir endereços de `entity`."""
    if user.is_staff:
        return True
    if isinstance(entity, User):
        return entity.pk == user.pk
    if isinstance(entity, Restaurant):
        return entity.owner == user
    return False


class IsEntityOwnerOrAdmin(BasePermission):
    """Objeto Address: dono da entidade ligada (User/Restaurant) ou admin.
    Sem leitura pública — endereço é dado privado."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = cast(User, request.user)
        entity = obj.entity
        if entity is None:
            return user.is_staff
        return owns_entity(user, entity)
