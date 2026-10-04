from django.urls import path

from .views import PromotionEndView, PromotionListCreateView

urlpatterns = [
    path("<int:restaurant_pk>/promotions/", PromotionListCreateView.as_view(), name="promotion-list-create"),
    path("<int:restaurant_pk>/promotions/<int:pk>/", PromotionEndView.as_view(), name="promotion-end"),
]
