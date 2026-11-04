import uuid
from django.conf import settings
from django.db import models


class AnalyticsEvent(models.Model):
    class Kind(models.TextChoices):
        IMPRESSION = 'result_impression', 'Aparição em resultados'
        VIEW = 'detail_view', 'Abertura de detalhe'
        CONTACT = 'contact_click', 'Clique em contato'
        MENU = 'menu_click', 'Abertura de cardápio'
        DIRECTIONS = 'directions_click', 'Clique em rota'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE)
    promotion = models.ForeignKey('promotions.Promotion', null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    channel = models.CharField(max_length=15, default='web')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['restaurant', 'created_at', 'kind']), models.Index(fields=['created_at'])]


class PromotionRedemption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE)
    promotion = models.ForeignKey('promotions.Promotion', on_delete=models.PROTECT)
    reference = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['restaurant', 'reference'], name='unique_restaurant_redemption_reference')]
        indexes = [models.Index(fields=['restaurant', 'created_at'])]


class AnalyticsDaily(models.Model):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE)
    day = models.DateField()
    kind = models.CharField(max_length=30, choices=AnalyticsEvent.Kind.choices)
    count = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['restaurant', 'day', 'kind'], name='unique_restaurant_daily_metric')]


class OperationalBucket(models.Model):
    minute = models.DateTimeField()
    component = models.CharField(max_length=20, default='search')
    count = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveBigIntegerField(default=0)
    le100 = models.PositiveIntegerField(default=0)
    le500 = models.PositiveIntegerField(default=0)
    le1000 = models.PositiveIntegerField(default=0)
    le3000 = models.PositiveIntegerField(default=0)
    over3000 = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['minute', 'component'], name='unique_operational_minute')]
