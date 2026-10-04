from django.urls import path

from .views import PlatformMetricsView, RestaurantInsightsView

urlpatterns = [
    path("platform/", PlatformMetricsView.as_view(), name="platform-metrics"),
    path("restaurants/<int:pk>/", RestaurantInsightsView.as_view(), name="restaurant-insights"),
]
