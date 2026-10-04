from django.urls import path

from .views import (
    AmbientAffinityEditView,
    CuisineAffinityEditView,
    PreferencesView,
    PriceAffinityEditView,
    RankingWeightView,
    SearchHistoryView,
)

urlpatterns = [
    path("", PreferencesView.as_view(), name="preferences"),
    path("searches/", SearchHistoryView.as_view(), name="search-history"),
    path("weights/", RankingWeightView.as_view(), name="ranking-weights"),
    path("cuisines/<int:pk>/", CuisineAffinityEditView.as_view(), name="cuisine-affinity"),
    path("ambients/<int:pk>/", AmbientAffinityEditView.as_view(), name="ambient-affinity"),
    path("prices/<int:pk>/", PriceAffinityEditView.as_view(), name="price-affinity"),
]
