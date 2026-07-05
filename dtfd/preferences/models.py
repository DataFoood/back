from django.conf import settings
from django.db import models

from utils import AbstractAudit


class SearchHistory(models.Model):
    """Histórico de buscas do usuário. Substitui 'pedidos' como sinal de
    intenção recorrente — base de preferência secundária (peso baixo,
    não sobrepõe o texto da busca atual)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="searches"
    )
    query = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.query[:60]


class RankingWeight(models.Model):
    """Pesos do ranking do shinzou, gerenciáveis (admin). key-value pra
    adicionar sinais sem migration. Lido pelo shinzou via SQL."""

    key = models.CharField(max_length=50, unique=True)
    weight = models.FloatField(default=1.0)

    def __str__(self):
        return f"{self.key}={self.weight}"


class BaseAffinity(AbstractAudit):
    """Afinidade do usuário com um valor de taxonomia.

    `score` 0..1 normalizado (média ponderada de interações).
    `is_manual` = usuário editou -> o recompute NÃO sobrescreve."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0)
    is_manual = models.BooleanField(default=False)

    class Meta:
        abstract = True
        ordering = ["-score"]


class UserCuisineAffinity(BaseAffinity):
    cuisine = models.ForeignKey(
        "restaurants.Cuisine", on_delete=models.CASCADE, related_name="affinities"
    )

    class Meta(BaseAffinity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "cuisine"], name="unique_user_cuisine_affinity"
            )
        ]


class UserAmbientAffinity(BaseAffinity):
    ambient = models.ForeignKey(
        "restaurants.Ambient", on_delete=models.CASCADE, related_name="affinities"
    )

    class Meta(BaseAffinity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "ambient"], name="unique_user_ambient_affinity"
            )
        ]


class UserPriceAffinity(BaseAffinity):
    price_range = models.ForeignKey(
        "restaurants.PriceRange", on_delete=models.CASCADE, related_name="affinities"
    )

    class Meta(BaseAffinity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "price_range"], name="unique_user_price_affinity"
            )
        ]
