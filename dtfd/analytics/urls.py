from django.urls import path

from .views import PlatformMetricsView

urlpatterns = [
    path("platform/", PlatformMetricsView.as_view(), name="platform-metrics"),
]
