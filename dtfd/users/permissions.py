from typing import cast

from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import User


class IsOwnerOrAdmin(BasePermission):
    """Leitura livre para autenticados. Escrita só para dono ou admin."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = cast(User, request.user)
        return obj == user or user.is_staff
