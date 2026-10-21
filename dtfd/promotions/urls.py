from django.urls import path

from .views import (
    ActivePromotionsView,
    InfraSuggestionView,
    MessagingPreferenceView,
    PromotionAudienceView,
    PromotionDetailView,
    PromotionListCreateView,
    PromotionSendView,
    PromotionUnscheduleView,
    TelegramLinkView,
    UnsubscribeView,
)

# montado em /api/promotions/
urlpatterns = [
    path("preferences/", MessagingPreferenceView.as_view(), name="promotion-preferences"),
    path("preferences/telegram/", TelegramLinkView.as_view(), name="promotion-telegram-link"),
    path("unsubscribe/", UnsubscribeView.as_view(), name="promotion-unsubscribe"),
    path("infra-suggestion/", InfraSuggestionView.as_view(), name="promotion-infra-suggestion"),
]

# montado em /api/restaurants/ (aninhado no restaurante)
restaurant_urlpatterns = [
    path("<int:restaurant_pk>/promotions/",
         PromotionListCreateView.as_view(), name="promotion-list-create"),
    path("<int:restaurant_pk>/promotions/active/",
         ActivePromotionsView.as_view(), name="promotion-active"),
    path("<int:restaurant_pk>/promotions/audience/",
         PromotionAudienceView.as_view(), name="promotion-audience"),
    path("<int:restaurant_pk>/promotions/<int:pk>/",
         PromotionDetailView.as_view(), name="promotion-detail"),
    path("<int:restaurant_pk>/promotions/<int:pk>/send/",
         PromotionSendView.as_view(), name="promotion-send"),
    path("<int:restaurant_pk>/promotions/<int:pk>/unschedule/",
         PromotionUnscheduleView.as_view(), name="promotion-unschedule"),
]
