from typing import cast

from django.shortcuts import get_object_or_404
from rest_framework.permissions import BasePermission, SAFE_METHODS

from users.models import User

from .models import Restaurant


class IsRestaurantOwnerOrAdmin(BasePermission):
    """Leitura publica. Escrita so para o dono do restaurante ou admin."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = cast(User, request.user)
        return obj.owner == user or user.is_staff


class IsAuthorOrAdmin(BasePermission):
    """Review: leitura publica. Escrita so do autor ou admin."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = cast(User, request.user)
        return obj.author == user or user.is_staff


class IsParentRestaurantOwnerOrAdmin(BasePermission):
    """Nested (images/hours): leitura publica. Escrita so do dono do
    restaurante pai (lido de restaurant_pk na URL) ou admin."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        user = cast(User, request.user)
        restaurant = get_object_or_404(Restaurant, pk=view.kwargs["restaurant_pk"])
        return restaurant.owner == user or user.is_staff

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = cast(User, request.user)
        return obj.restaurant.owner == user or user.is_staff
