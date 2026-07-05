from typing import cast

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView

from restaurants.models import Restaurant
from users.models import User

from .models import Address
from .permissions import IsEntityOwnerOrAdmin, owns_entity
from .serializers import AddressSerializer


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
        serializer.save()


class AddressDetailView(RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE — só dono da entidade ligada ou admin. DELETE = soft."""
    serializer_class = AddressSerializer
    permission_classes = [IsEntityOwnerOrAdmin]
    queryset = Address.objects.all()

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])
