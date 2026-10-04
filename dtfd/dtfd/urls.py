from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from restaurants.views import SearchView

def health(request):
    """GET /api/health/ — liveness + banco (usado pelo healthcheck do compose)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error", "db": False}, status=503)
    return JsonResponse({"status": "ok", "db": True})


urlpatterns = [
    path("api/health/", health, name="health"),
    path("admin/", admin.site.urls),
    # OpenAPI schema + Swagger UI (handoff frontend)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/search/", SearchView.as_view(), name="search"),
    path("api/users/", include("users.urls")),
    path("api/restaurants/", include("restaurants.urls")),
    path("api/addresses/", include("address.urls")),
    path("api/preferences/", include("preferences.urls")),
    path("api/analytics/", include("analytics.urls")),
]
