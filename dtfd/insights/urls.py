from django.urls import path
from .views import EventView, AnalyticsView, RedemptionView

urlpatterns = [path('events/', EventView.as_view(), name='analytics-event')]
restaurant_urlpatterns = [
    path('<int:restaurant_pk>/analytics/', AnalyticsView.as_view(), name='restaurant-analytics'),
    path('<int:restaurant_pk>/redemptions/', RedemptionView.as_view(), name='restaurant-redemptions'),
]
