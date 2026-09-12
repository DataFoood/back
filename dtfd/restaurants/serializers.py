from django.utils.text import slugify
from rest_framework import serializers

from .models import (
    Ambient,
    BusinessHour,
    BusinessModel,
    Cuisine,
    PhysicalFormat,
    PriceRange,
    Restaurant,
    RestaurantFavorite,
    RestaurantImage,
    RestaurantItem,
    RestaurantReview,
    ServiceModel,
    TargetAudience,
)


class LookupSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class RestaurantItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantItem
        fields = ["id", "restaurant", "name", "description", "price", "position", "created_at"]
        read_only_fields = ["id", "restaurant", "created_at"]


class RestaurantFavoriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantFavorite
        fields = ["id", "restaurant", "created_at"]
        read_only_fields = ["id", "restaurant", "created_at"]


class RestaurantImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantImage
        fields = ["id", "url", "created_at"]
        read_only_fields = ["id", "created_at"]


class RestaurantReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantReview
        fields = ["id", "restaurant", "author", "title", "description", "rating", "created_at"]
        read_only_fields = ["id", "restaurant", "author", "created_at"]


class BusinessHourSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessHour
        fields = ["id", "restaurant", "day_week", "meta_interval", "is_closed", "created_at"]
        read_only_fields = ["id", "restaurant", "created_at"]

    def validate_meta_interval(self, value):
        """Estrutura esperada: {"lunch": ["HH:MM:SS", "HH:MM:SS"], ...}.
        Cada intervalo = lista [inicio, fim] com fim > inicio."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Deve ser um objeto {periodo: [inicio, fim]}.")
        for period, interval in value.items():
            if not isinstance(interval, list) or len(interval) != 2:
                raise serializers.ValidationError(f"'{period}': esperado [inicio, fim].")
            start, end = interval
            if not (_is_time(start) and _is_time(end)):
                raise serializers.ValidationError(f"'{period}': horario deve ser HH:MM:SS.")
            if end <= start:
                raise serializers.ValidationError(f"'{period}': fim deve ser maior que inicio.")
        return value


def _is_time(value):
    import datetime
    try:
        datetime.time.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


SALES_CHANNEL_FIELDS = [
    "has_dine_in", "has_delivery", "has_take_out", "has_drive_thru",
    "has_reservation", "accepts_vale_refeicao", "accepts_online_order",
]
TAXONOMY_FIELDS = [
    "cuisines", "ambients", "service_models", "target_audiences",
    "price_ranges", "business_models", "physical_formats",
]


class RestaurantReadSerializer(serializers.ModelSerializer):
    images = RestaurantImageSerializer(many=True, read_only=True)
    reviews = RestaurantReviewSerializer(many=True, read_only=True)
    business_hours = BusinessHourSerializer(many=True, read_only=True)
    items = RestaurantItemSerializer(many=True, read_only=True)

    cuisines = LookupSerializer(many=True, read_only=True)
    ambients = LookupSerializer(many=True, read_only=True)
    service_models = LookupSerializer(many=True, read_only=True)
    target_audiences = LookupSerializer(many=True, read_only=True)
    price_ranges = LookupSerializer(many=True, read_only=True)
    business_models = LookupSerializer(many=True, read_only=True)
    physical_formats = LookupSerializer(many=True, read_only=True)

    class Meta:
        model = Restaurant
        fields = [
            "id", "owner", "name", "slug", "description", "cnpj", "phone",
            "email", "website", "average_rating", "total_reviews",
            "cover_image", "menu_url", "created_at", "updated_at",
            "images", "reviews", "business_hours", "items",
            *TAXONOMY_FIELDS, *SALES_CHANNEL_FIELDS,
        ]


class RestaurantWriteSerializer(serializers.ModelSerializer):
    cuisines = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=Cuisine.objects.all())
    ambients = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=Ambient.objects.all())
    service_models = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=ServiceModel.objects.all())
    target_audiences = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=TargetAudience.objects.all())
    price_ranges = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=PriceRange.objects.all())
    business_models = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=BusinessModel.objects.all())
    physical_formats = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=PhysicalFormat.objects.all())

    class Meta:
        model = Restaurant
        fields = [
            "id", "name", "description", "cnpj", "phone", "email",
            "website", "cover_image", "menu_url",
            *TAXONOMY_FIELDS, *SALES_CHANNEL_FIELDS,
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        validated_data["slug"] = self._unique_slug(validated_data["name"])
        return super().create(validated_data)

    def _unique_slug(self, name):
        base = slugify(name)
        slug = base
        i = 1
        while Restaurant.all_objects.filter(slug=slug).exists():
            i += 1
            slug = f"{base}-{i}"
        return slug
