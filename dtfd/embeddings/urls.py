from django.urls import path

from .views import ReindexView

urlpatterns = [
    path("reindex/", ReindexView.as_view(), name="reindex"),
]
