from typing import cast

from django.shortcuts import get_object_or_404
from rest_framework.permissions import BasePermission

from restaurants.models import Restaurant
from users.models import User


class IsRestaurantManager(BasePermission):
    """Promoções: leitura E escrita só do dono do restaurante (restaurant_pk
    na URL) ou admin — rascunho e números de envio não são públicos."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        user = cast(User, request.user)
        restaurant = get_object_or_404(Restaurant, pk=view.kwargs["restaurant_pk"])
        return restaurant.owner == user or user.is_staff


class IsOwnerRoleOrAdmin(BasePermission):
    """Conta de restaurante (role owner) ou admin."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        user = cast(User, request.user)
        return user.is_staff or user.role in (User.Role.OWNER, User.Role.ADMIN)
