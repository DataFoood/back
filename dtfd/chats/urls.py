from django.urls import path

from .views import ChatDetailView, ChatListCreateView
from .assistant_views import ChatRecommendationsView, ChatRespondView

urlpatterns = [
    path("", ChatListCreateView.as_view(), name="chat-list-create"),
    path("respond/", ChatRespondView.as_view(), name="chat-respond"),
    path("<int:pk>/recommendations/<int:message_index>/", ChatRecommendationsView.as_view(), name="chat-recommendations"),
    path("<int:pk>/", ChatDetailView.as_view(), name="chat-detail"),
]
