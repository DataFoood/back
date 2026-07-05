"""
URL configuration for dtfd project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from restaurants.views import SearchView

urlpatterns = [
    path("admin/", admin.site.urls),
    # OpenAPI schema + Swagger UI (handoff frontend)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/search/", SearchView.as_view(), name="search"),
    path("api/users/", include("users.urls")),
    path("api/restaurants/", include("restaurants.urls")),
    path("api/addresses/", include("address.urls")),
    path("api/preferences/", include("preferences.urls")),
    path("api/embeddings/", include("embeddings.urls")),
]
