from django.urls import path

from .views import (
    BusinessHourDetailView,
    BusinessHourListCreateView,
    FavoriteListView,
    FavoriteToggleView,
    ImageDetailView,
    ImageListCreateView,
    ItemDetailView,
    ItemListCreateView,
    MyRestaurantsView,
    RestaurantStatsView,
    TaxonomiesView,
    RestaurantDetailView,
    RestaurantListCreateView,
    ReviewDetailView,
    ReviewListCreateView,
)

urlpatterns = [
    path("", RestaurantListCreateView.as_view(), name="restaurant-list-create"),
    path("favorites/", FavoriteListView.as_view(), name="favorite-list"),
    path("mine/", MyRestaurantsView.as_view(), name="restaurant-mine"),
    path("taxonomies/", TaxonomiesView.as_view(), name="restaurant-taxonomies"),
    path("by-slug/<slug:slug>/", RestaurantDetailView.as_view(), name="restaurant-by-slug"),
    path("<int:pk>/", RestaurantDetailView.as_view(), name="restaurant-detail"),
    path("<int:pk>/stats/", RestaurantStatsView.as_view(), name="restaurant-stats"),
    path("<int:pk>/favorite/", FavoriteToggleView.as_view(), name="restaurant-favorite"),

    path("<int:restaurant_pk>/items/",
         ItemListCreateView.as_view(), name="item-list-create"),
    path("<int:restaurant_pk>/items/<int:pk>/",
         ItemDetailView.as_view(), name="item-detail"),

    path("<int:restaurant_pk>/reviews/",
         ReviewListCreateView.as_view(), name="review-list-create"),
    path("<int:restaurant_pk>/reviews/<int:pk>/",
         ReviewDetailView.as_view(), name="review-detail"),

    path("<int:restaurant_pk>/images/",
         ImageListCreateView.as_view(), name="image-list-create"),
    path("<int:restaurant_pk>/images/<int:pk>/",
         ImageDetailView.as_view(), name="image-detail"),

    path("<int:restaurant_pk>/hours/",
         BusinessHourListCreateView.as_view(), name="hour-list-create"),
    path("<int:restaurant_pk>/hours/<int:pk>/",
         BusinessHourDetailView.as_view(), name="hour-detail"),
]
