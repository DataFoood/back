from typing import cast

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView

from restaurants.models import Restaurant
from users.models import User

from .models import Address
from .permissions import IsEntityOwnerOrAdmin, owns_entity
from .serializers import AddressSerializer
from .tasks import geocode_address

# mudou um destes -> coordenada antiga não vale mais
LOCATION_FIELDS = {"street", "number", "city", "state", "zipcode", "country"}


def geocode_if_needed(address, changed: set[str]):
    """Só endereço de restaurante (público) vai pro Nominatim; coordenada
    enviada explicitamente pelo dono é respeitada."""
    if address.content_type.model != "restaurant" or "latitude" in changed:
        return
    if address.latitude is None or changed & LOCATION_FIELDS:
        # depois do commit: o worker precisa enxergar a linha
        transaction.on_commit(lambda: geocode_address.delay(address.pk))


class AddressListCreateView(ListCreateAPIView):
    """GET — endereços que o usuário pode ver (próprios + dos seus restaurantes).
       POST — cria endereço para entidade que o usuário possui."""
    serializer_class = AddressSerializer
    permission_classes = [IsEntityOwnerOrAdmin]

    def get_queryset(self):
        user = cast(User, self.request.user)
        if user.is_staff:
            return Address.objects.all()
        user_ct = ContentType.objects.get_for_model(User)
        rest_ct = ContentType.objects.get_for_model(Restaurant)
        owned_rest_ids = Restaurant.objects.filter(owner=user).values_list("id", flat=True)
        return Address.objects.filter(
            Q(content_type=user_ct, object_id=user.pk)
            | Q(content_type=rest_ct, object_id__in=owned_rest_ids)
        )

    def perform_create(self, serializer):
        content_type = serializer.validated_data["content_type"]
        object_id = serializer.validated_data["object_id"]
        entity = content_type.get_object_for_this_type(pk=object_id)
        if not owns_entity(cast(User, self.request.user), entity):
            raise PermissionDenied("Você não pode criar endereço para esta entidade.")
        address = serializer.save()
        geocode_if_needed(address, set(serializer.validated_data))


class AddressDetailView(RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE — só dono da entidade ligada ou admin. DELETE = soft."""
    serializer_class = AddressSerializer
    permission_classes = [IsEntityOwnerOrAdmin]
    queryset = Address.objects.all()

    def perform_update(self, serializer):
        address = serializer.save()
        geocode_if_needed(address, set(serializer.validated_data))

    def perform_destroy(self, instance):
        instance.soft_delete()
