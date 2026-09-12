from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from utils import AbstractAudit


# --- Taxonomias (lookup tables, semeadas via data migration) ---------------
class BaseLookup(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class Cuisine(BaseLookup):
    pass


class Ambient(BaseLookup):
    pass


class ServiceModel(BaseLookup):
    pass


class TargetAudience(BaseLookup):
    pass


class PriceRange(BaseLookup):
    pass


class BusinessModel(BaseLookup):
    pass


class PhysicalFormat(BaseLookup):
    pass


class Restaurant(AbstractAudit):
    class Origin(models.TextChoices):
        MANUAL = "manual", "Manual (site)"
        GOOGLE = "google", "Google Places"

    # owner: adicionado (não estava na lista). Nullable pra não travar criação.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restaurants",
    )

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)
    cnpj = models.CharField(max_length=14, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    # denormalizados: cache de agregação das reviews, NÃO fonte da verdade.
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_reviews = models.PositiveIntegerField(default=0)
    cover_image = models.URLField(blank=True)
    menu_url = models.URLField(blank=True)

    # Taxonomias — todas M2M (pivo automatico)
    cuisines = models.ManyToManyField(Cuisine, blank=True, related_name="restaurants")
    ambients = models.ManyToManyField(Ambient, blank=True, related_name="restaurants")
    service_models = models.ManyToManyField(ServiceModel, blank=True, related_name="restaurants")
    target_audiences = models.ManyToManyField(TargetAudience, blank=True, related_name="restaurants")
    price_ranges = models.ManyToManyField(PriceRange, blank=True, related_name="restaurants")
    business_models = models.ManyToManyField(BusinessModel, blank=True, related_name="restaurants")
    physical_formats = models.ManyToManyField(PhysicalFormat, blank=True, related_name="restaurants")

    # Fonte do cadastro (manual no site, importado do Google, etc).
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.MANUAL)
    # id externo (ex: place_id do Google) pra evitar duplicata em reimportacao.
    external_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    # Reindexacao: True = precisa (re)gerar embedding. Marcado por signal
    # quando dado relevante muda; ingestao processa os stale e reseta.
    embedding_stale = models.BooleanField(default=True)

    # Sales channel — flags booleanas
    has_dine_in = models.BooleanField(default=False)
    has_delivery = models.BooleanField(default=False)
    has_take_out = models.BooleanField(default=False)
    has_drive_thru = models.BooleanField(default=False)
    has_reservation = models.BooleanField(default=False)
    accepts_vale_refeicao = models.BooleanField(default=False)
    accepts_online_order = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "id"]  # paginação determinística

    def __str__(self):
        return self.name

    def recalc_rating(self):
        """Recalcula os campos denormalizados a partir das reviews ativas.
        Usa o manager padrão de RestaurantReview -> ignora soft-deleted."""
        from django.db.models import Avg

        reviews = RestaurantReview.objects.filter(restaurant=self)
        agg = reviews.aggregate(avg=Avg("rating"))
        self.average_rating = round(agg["avg"] or 0, 2)
        self.total_reviews = reviews.count()
        self.save(update_fields=["average_rating", "total_reviews"])


class RestaurantImage(AbstractAudit):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="images"
    )
    url = models.URLField()

    def __str__(self):
        return self.url


class RestaurantReview(AbstractAudit):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="reviews"
    )
    # author: adicionado (não estava na lista). Nullable.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    title = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    def __str__(self):
        return f"{self.rating}★ {self.title}".strip()


class BusinessHour(AbstractAudit):
    class DayWeek(models.IntegerChoices):
        MONDAY = 0, "Segunda"
        TUESDAY = 1, "Terça"
        WEDNESDAY = 2, "Quarta"
        THURSDAY = 3, "Quinta"
        FRIDAY = 4, "Sexta"
        SATURDAY = 5, "Sábado"
        SUNDAY = 6, "Domingo"

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="business_hours"
    )
    day_week = models.IntegerField(choices=DayWeek.choices)
    # ex: {"lunch": ["11:00:00", "15:00:00"], "dinner": ["18:00:00", "23:00:00"]}
    # validação do formato/constraint de horário fica no serializer.
    meta_interval = models.JSONField(default=dict, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "day_week"], name="unique_restaurant_day"
            )
        ]

    def __str__(self):
        return self.DayWeek(self.day_week).label


# --- Fase 1: dados-sinal pra busca semantica -------------------------------
class RestaurantItem(AbstractAudit):
    """Pratos principais do restaurante (ate 6). Alimenta o embedding e o
    casamento por comida ('tenha feijoada'). Limite de 6 validado no serializer."""

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="items"
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.name


class RestaurantFavorite(AbstractAudit):
    """Pivo user x restaurante. Sinal forte de preferencia (peso maior que view)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="favorited_by"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "restaurant"], name="unique_user_favorite"
            )
        ]

    def __str__(self):
        return f"favorite {self.pk}"


class RestaurantView(AbstractAudit):
    """Pivo user x restaurante agregado. `count` = frequencia de visualizacao,
    sinal fraco de preferencia. updated_at = ultima visualizacao."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="restaurant_views"
    )
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="views"
    )
    count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "restaurant"], name="unique_user_view"
            )
        ]

    def __str__(self):
        return f"view x{self.count}"
