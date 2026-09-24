import datetime

from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from address.models import Address

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
    restaurant = serializers.SerializerMethodField()

    class Meta:
        model = RestaurantFavorite
        fields = ["id", "restaurant", "created_at"]
        read_only_fields = ["id", "restaurant", "created_at"]

    @extend_schema_field(serializers.DictField())
    def get_restaurant(self, obj):
        return RestaurantCardSerializer(obj.restaurant, context=self.context).data


class RestaurantImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantImage
        fields = ["id", "url", "created_at"]
        read_only_fields = ["id", "created_at"]


class RestaurantReviewSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = RestaurantReview
        fields = ["id", "restaurant", "author", "author_name", "title",
                  "description", "rating", "created_at"]
        read_only_fields = ["id", "restaurant", "author", "author_name", "created_at"]

    def get_author_name(self, obj) -> str:
        # só o primeiro nome: review é pública, nome completo é dado pessoal
        if obj.author is None:
            return "anônimo"
        return (obj.author.name or "").split(" ")[0] or "anônimo"


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


class RestaurantAddressSerializer(serializers.ModelSerializer):
    """Endereço do restaurante — público (diferente do endereço de usuário)."""

    class Meta:
        model = Address
        fields = ["id", "street", "number", "complement", "neighborhood", "city",
                  "state", "zipcode", "latitude", "longitude"]
        read_only_fields = fields


def primary_address(restaurant):
    """Endereço default do restaurante (ou o primeiro). Usa o prefetch."""
    addresses = list(restaurant.addresses.all())
    if not addresses:
        return None
    return next((a for a in addresses if a.is_default), addresses[0])


def is_open_now(restaurant, now=None) -> bool | None:
    """True/False conforme os horários cadastrados; None se não há horários."""
    hours = list(restaurant.business_hours.all())
    if not hours:
        return None
    now = timezone.localtime(now)
    today = next((h for h in hours if h.day_week == now.weekday()), None)
    if today is None or today.is_closed:
        return False
    current = now.time().replace(microsecond=0)
    for start, end in (today.meta_interval or {}).values():
        if datetime.time.fromisoformat(start) <= current < datetime.time.fromisoformat(end):
            return True
    return False


SALES_CHANNEL_FIELDS = [
    "has_dine_in", "has_delivery", "has_take_out", "has_drive_thru",
    "has_reservation", "accepts_vale_refeicao", "accepts_online_order",
]
TAXONOMY_FIELDS = [
    "cuisines", "ambients", "service_models", "target_audiences",
    "price_ranges", "business_models", "physical_formats",
]


class _RestaurantComputedMixin(serializers.Serializer):
    address = serializers.SerializerMethodField()
    is_open_now = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()

    @extend_schema_field(RestaurantAddressSerializer(allow_null=True))
    def get_address(self, obj):
        address = primary_address(obj)
        return RestaurantAddressSerializer(address).data if address else None

    def get_is_open_now(self, obj) -> bool | None:
        return is_open_now(obj)

    def get_is_favorited(self, obj) -> bool:
        # conjunto pré-calculado pela view (evita N+1); senão consulta direto
        favorited = self.context.get("favorited_ids")
        if favorited is not None:
            return obj.pk in favorited
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return RestaurantFavorite.objects.filter(user=request.user, restaurant=obj).exists()


class RestaurantCardSerializer(_RestaurantComputedMixin, serializers.ModelSerializer):
    """Versão enxuta pra listas, busca e favoritos."""
    cuisines = LookupSerializer(many=True, read_only=True)
    ambients = LookupSerializer(many=True, read_only=True)
    price_ranges = LookupSerializer(many=True, read_only=True)

    class Meta:
        model = Restaurant
        fields = [
            "id", "name", "slug", "description", "cover_image",
            "average_rating", "total_reviews", "cuisines", "ambients",
            "price_ranges", "address", "is_open_now", "is_favorited",
            "has_delivery", "has_reservation",
        ]
        read_only_fields = fields


CARD_PREFETCH = ["cuisines", "ambients", "price_ranges", "addresses", "business_hours"]


class RestaurantReadSerializer(_RestaurantComputedMixin, serializers.ModelSerializer):
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
            "address", "is_open_now", "is_favorited",
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
