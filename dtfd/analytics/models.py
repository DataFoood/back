"""Métricas agregadas e anônimas: só contagens, nenhum vínculo com usuário.
Região = célula de ~1 km (coordenada arredondada em 2 casas)."""

from django.db import models


class GeoCell(models.Model):
    """Célula geográfica (~1 km) com nome legível (reverse geocoding, lazy)."""
    lat = models.DecimalField(max_digits=5, decimal_places=2)
    lon = models.DecimalField(max_digits=5, decimal_places=2)
    label = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lat", "lon"], name="unique_geo_cell")]

    def __str__(self):
        return self.label or f"{self.lat}, {self.lon}"


class AccessStat(models.Model):
    """Tabela fato: quantos acessos houve por restaurante × dia × hora ×
    evento × faixa etária × célula. A célula é nula quando o visitante não
    ligou a localização; a faixa é "unknown" sem consentimento ou sem data
    de nascimento."""

    class Event(models.TextChoices):
        IMPRESSION = "impression", "Apareceu num resultado da busca"
        VIEW = "view", "Abriu o detalhe (acesso direto)"
        SEARCH_VIEW = "search_view", "Abriu o detalhe a partir da busca"

    class Age(models.TextChoices):
        UNDER_18 = "lt18", "Menos de 18"
        AGE_18_24 = "18-24", "18 a 24"
        AGE_25_39 = "25-39", "25 a 39"
        AGE_40_59 = "40-59", "40 a 59"
        AGE_60_PLUS = "60+", "60 ou mais"
        UNKNOWN = "unknown", "Não informado"

    restaurant = models.ForeignKey(
        "restaurants.Restaurant", on_delete=models.CASCADE, related_name="access_stats"
    )
    date = models.DateField()
    hour = models.PositiveSmallIntegerField()  # 0-23, horário de Brasília
    event = models.CharField(max_length=12, choices=Event.choices)
    age = models.CharField(max_length=8, choices=Age.choices, default=Age.UNKNOWN)
    cell = models.ForeignKey(GeoCell, null=True, blank=True, on_delete=models.CASCADE, related_name="accesses")
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "date", "hour", "event", "age", "cell"],
                name="unique_access_stat",
                nulls_distinct=False,  # cell nula também é uma chave única
            )
        ]
        indexes = [models.Index(fields=["restaurant", "date"])]


class PlatformDailyStat(models.Model):
    date = models.DateField(unique=True)
    searches = models.PositiveIntegerField(default=0)
    search_failures = models.PositiveIntegerField(default=0)
