from django.urls import path

from .views import AddressDetailView, AddressListCreateView

urlpatterns = [
    path("", AddressListCreateView.as_view(), name="address-list-create"),
    path("<int:pk>/", AddressDetailView.as_view(), name="address-detail"),
]
