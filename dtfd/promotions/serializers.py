from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch
from django.db.models.functions import Now
from django.utils import timezone
from rest_framework import serializers

from .models import FlashPromotion, PromotionItem

MAX_DURATION = timedelta(hours=24)  # relâmpago: no máximo um dia
MAX_PERCENT = Decimal("90")


def active_promotions_prefetch(prefix: str = "") -> Prefetch:
    """Promoções ativas → `obj.active_promotions`. Now() é avaliado no SQL de cada consulta."""
    return Prefetch(
        f"{prefix}promotions",
        queryset=FlashPromotion.objects.filter(starts_at__lte=Now(), ends_at__gt=Now()).prefetch_related("items__item"),
        to_attr="active_promotions",
    )


def current_promotion(restaurant):
    """Promoção ativa do restaurante (usa o prefetch quando houver)."""
    promos = getattr(restaurant, "active_promotions", None)
    if promos is None:
        promos = list(restaurant.promotions.active().prefetch_related("items__item"))
    return promos[0] if promos else None


class PromotionItemSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="item.name", read_only=True)
    price = serializers.DecimalField(source="item.price", max_digits=10, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PromotionItem
        fields = ["item", "name", "price", "final_price", "discount_type", "discount_value"]


class FlashPromotionSerializer(serializers.ModelSerializer):
    """Criação e leitura. Depois de criada só pode ser encerrada (DELETE)."""
    items = PromotionItemSerializer(many=True)
    is_active = serializers.BooleanField(read_only=True)
    starts_at = serializers.DateTimeField(required=False)

    class Meta:
        model = FlashPromotion
        fields = ["id", "title", "starts_at", "ends_at", "is_active", "items", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_items(self, items):
        restaurant = self.context["restaurant"]
        if not items:
            raise serializers.ValidationError("Escolha pelo menos um item do cardápio.")
        seen = set()
        for row in items:
            item, kind, value = row["item"], row["discount_type"], row["discount_value"]
            if item.restaurant_id != restaurant.pk:
                raise serializers.ValidationError(f"“{item.name}” não é do seu cardápio.")
            if item.pk in seen:
                raise serializers.ValidationError(f"“{item.name}” aparece duas vezes.")
            seen.add(item.pk)
            if item.price is None:
                raise serializers.ValidationError(f"“{item.name}” não tem preço: cadastre o preço antes.")
            if kind == PromotionItem.DiscountType.PERCENT and not 0 < value <= MAX_PERCENT:
                raise serializers.ValidationError(f"“{item.name}”: desconto entre 1% e {MAX_PERCENT}%.")
            if kind == PromotionItem.DiscountType.AMOUNT and not 0 < value < item.price:
                raise serializers.ValidationError(f"“{item.name}”: desconto maior que zero e menor que R$ {item.price}.")
        return items

    def validate(self, attrs):
        now = timezone.now()
        starts = attrs.get("starts_at") or now
        ends = attrs["ends_at"]
        if starts < now - timedelta(minutes=5):
            raise serializers.ValidationError({"starts_at": "Não dá para começar no passado."})
        if starts > now + timedelta(days=7):
            raise serializers.ValidationError({"starts_at": "Agende no máximo com 7 dias de antecedência."})
        if ends <= starts:
            raise serializers.ValidationError({"ends_at": "A expiração precisa ser depois do início."})
        if ends - starts > MAX_DURATION:
            raise serializers.ValidationError({"ends_at": "Promoção relâmpago dura no máximo 24 horas."})
        clash = FlashPromotion.objects.filter(
            restaurant=self.context["restaurant"], starts_at__lt=ends, ends_at__gt=starts
        ).first()
        if clash:
            local = timezone.localtime(clash.ends_at).strftime("%d/%m %H:%M")
            raise serializers.ValidationError({"detail": f"Já existe uma promoção nesse horário (até {local}). Encerre-a antes."})
        attrs["starts_at"] = starts
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        promotion = FlashPromotion.objects.create(restaurant=self.context["restaurant"], **validated_data)
        PromotionItem.objects.bulk_create([PromotionItem(promotion=promotion, **row) for row in items])
        return promotion


class PromotionSummarySerializer(serializers.ModelSerializer):
    """Resumo pros cards (listas, busca, favoritos)."""
    items_count = serializers.SerializerMethodField()
    max_discount_percent = serializers.SerializerMethodField()

    class Meta:
        model = FlashPromotion
        fields = ["id", "title", "ends_at", "items_count", "max_discount_percent"]

    def get_items_count(self, obj) -> int:
        return len(obj.items.all())

    def get_max_discount_percent(self, obj) -> int:
        """Maior desconto em % (o de valor convertido pelo preço do item)."""
        best = Decimal("0")
        for row in obj.items.all():
            price = row.item.price or Decimal("0")
            if price:
                best = max(best, (price - row.final_price) / price * 100)
        return int(best.to_integral_value())
