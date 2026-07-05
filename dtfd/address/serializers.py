from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from .models import Address

# entity_type (string da API) -> (app_label, model) do ContentType
ENTITY_MODELS = {
    "user": ("users", "user"),
    "restaurant": ("restaurants", "restaurant"),
}


class AddressSerializer(serializers.ModelSerializer):
    entity_type = serializers.CharField(write_only=True)

    class Meta:
        model = Address
        fields = [
            "id", "entity_type", "object_id", "label", "street", "number",
            "complement", "neighborhood", "city", "state", "country",
            "zipcode", "latitude", "longitude", "is_default", "geocoded_at",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_entity_type(self, value):
        value = value.lower()
        if value not in ENTITY_MODELS:
            raise serializers.ValidationError(
                f"entity_type deve ser um de {sorted(ENTITY_MODELS)}."
            )
        return value

    def validate(self, attrs):
        entity_type = attrs.get("entity_type")
        object_id = attrs.get("object_id")
        if entity_type and object_id is not None:
            app_label, model = ENTITY_MODELS[entity_type]
            content_type = ContentType.objects.get(app_label=app_label, model=model)
            model_cls = content_type.model_class()
            if model_cls is None:
                raise serializers.ValidationError({"entity_type": "Tipo inválido."})
            if not model_cls.objects.filter(pk=object_id).exists():
                raise serializers.ValidationError(
                    {"object_id": "Entidade alvo não encontrada."}
                )
            attrs["content_type"] = content_type
        return attrs

    def create(self, validated_data):
        validated_data.pop("entity_type")
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # entity não muda em update; descarta se vier
        validated_data.pop("entity_type", None)
        validated_data.pop("content_type", None)
        validated_data.pop("object_id", None)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["entity_type"] = instance.content_type.model
        return rep
