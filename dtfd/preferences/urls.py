from django.urls import path

from .views import (
    AmbientAffinityEditView,
    CuisineAffinityEditView,
    PreferencesView,
    PriceAffinityEditView,
    RecomputeView,
    SearchHistoryView,
)

urlpatterns = [
    path("", PreferencesView.as_view(), name="preferences"),
    path("searches/", SearchHistoryView.as_view(), name="search-history"),
    path("recompute/", RecomputeView.as_view(), name="recompute"),
    path("cuisines/<int:pk>/", CuisineAffinityEditView.as_view(), name="cuisine-affinity"),
    path("ambients/<int:pk>/", AmbientAffinityEditView.as_view(), name="ambient-affinity"),
    path("prices/<int:pk>/", PriceAffinityEditView.as_view(), name="price-affinity"),
]
