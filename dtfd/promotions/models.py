"""Promoção relâmpago: o dono põe itens do cardápio com desconto até uma hora
de expiração (ex.: perto do fechamento, pra não sobrar insumo)."""

from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone

CENTS = Decimal("0.01")


class FlashPromotionQuerySet(models.QuerySet):
    def active(self, at=None):
        at = at or timezone.now()
        return self.filter(starts_at__lte=at, ends_at__gt=at)


class FlashPromotion(models.Model):
    restaurant = models.ForeignKey(
        "restaurants.Restaurant", on_delete=models.CASCADE, related_name="promotions"
    )
    title = models.CharField(max_length=120, blank=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FlashPromotionQuerySet.as_manager()

    class Meta:
        ordering = ["-starts_at"]
        indexes = [models.Index(fields=["restaurant", "ends_at"])]

    def __str__(self):
        return self.title or f"promoção {self.pk}"

    @property
    def is_active(self) -> bool:
        return self.starts_at <= timezone.now() < self.ends_at


class PromotionItem(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Porcentagem"
        AMOUNT = "amount", "Valor (R$)"

    promotion = models.ForeignKey(FlashPromotion, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey("restaurants.RestaurantItem", on_delete=models.CASCADE, related_name="promotions")
    discount_type = models.CharField(max_length=8, choices=DiscountType.choices)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["promotion", "item"], name="unique_promotion_item")
        ]

    @property
    def final_price(self) -> Decimal:
        """Preço com desconto, em centavos, nunca negativo. Só visual: o
        restaurante cobra no balcão."""
        price = self.item.price or Decimal("0")
        if self.discount_type == self.DiscountType.PERCENT:
            final = price * (Decimal("100") - self.discount_value) / Decimal("100")
        else:
            final = price - self.discount_value
        return max(Decimal("0"), final).quantize(CENTS, rounding=ROUND_HALF_UP)
