from django.urls import path

from .premium import PremiumCouponView

from .views import (
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
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
    path("login/refresh/", RefreshView.as_view(), name="user-login-refresh"),
    path("logout/", LogoutView.as_view(), name="user-logout"),
    path("me/", MeView.as_view(), name="user-me"),
    path("premium/redeem/", PremiumCouponView.as_view(), name="premium-redeem"),
    path("removed/", UserRemovedListView.as_view(), name="user-removed"),
    path("consent/", UserConsentView.as_view(), name="user-consent"),
    path("<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("<int:pk>/delete/", UserDeleteView.as_view(), name="user-delete"),
    path("<int:pk>/change-password/", UserChangePasswordView.as_view(), name="user-change-password"),
]
