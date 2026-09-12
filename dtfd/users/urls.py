from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginView,
    UserChangePasswordView,
    UserConsentView,
    UserCreateView,
    UserDeleteView,
    UserDetailView,
    UserListView,
    UserRemovedListView,
)

urlpatterns = [
    path("", UserListView.as_view(), name="user-list"),
    path("register/", UserCreateView.as_view(), name="user-register"),
    path("login/", LoginView.as_view(), name="user-login"),
    path("login/refresh/", TokenRefreshView.as_view(), name="user-login-refresh"),
    path("removed/", UserRemovedListView.as_view(), name="user-removed"),
    path("consent/", UserConsentView.as_view(), name="user-consent"),
    path("<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("<int:pk>/delete/", UserDeleteView.as_view(), name="user-delete"),
    path("<int:pk>/change-password/", UserChangePasswordView.as_view(), name="user-change-password"),
]
