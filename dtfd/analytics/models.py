"""Métricas agregadas e anônimas: contadores por dia, nenhum vínculo com
usuário. Região = célula de ~1 km (coordenada arredondada em 2 casas)."""

from django.db import models


class RestaurantDailyStat(models.Model):
    restaurant = models.ForeignKey(
        "restaurants.Restaurant", on_delete=models.CASCADE, related_name="daily_stats"
    )
    date = models.DateField()
    views = models.PositiveIntegerField(default=0)
    # apareceu nos resultados de uma busca semântica (chat)
    search_impressions = models.PositiveIntegerField(default=0)
    # abriu o detalhe a partir de um resultado de busca
    search_clicks = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "date"], name="unique_restaurant_daily_stat")
        ]


class GeoCell(models.Model):
    """Célula geográfica (~1 km) com nome legível (reverse geocoding, lazy)."""
    lat = models.DecimalField(max_digits=5, decimal_places=2)
    lon = models.DecimalField(max_digits=5, decimal_places=2)
    label = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lat", "lon"], name="unique_geo_cell")]

    def __str__(self):
        return self.label or f"{self.lat}, {self.lon}"


class RegionVisit(models.Model):
    restaurant = models.ForeignKey(
        "restaurants.Restaurant", on_delete=models.CASCADE, related_name="region_visits"
    )
    cell = models.ForeignKey(GeoCell, on_delete=models.CASCADE, related_name="visits")
    date = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "cell", "date"], name="unique_region_visit")
        ]


class PlatformDailyStat(models.Model):
    date = models.DateField(unique=True)
    searches = models.PositiveIntegerField(default=0)
    search_failures = models.PositiveIntegerField(default=0)
