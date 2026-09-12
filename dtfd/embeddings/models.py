from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class RestaurantEmbedding(models.Model):
    """Vetor de embedding do restaurante (1:1). Guardado no mesmo Postgres
    via pgvector. shinzou faz kNN direto nesta tabela."""

    restaurant = models.OneToOneField(
        "restaurants.Restaurant", on_delete=models.CASCADE, related_name="embedding"
    )
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM)
    # documento texto que gerou o vetor (debug/auditoria) + modelo usado
    document = models.TextField()
    model = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"embedding {self.pk} ({self.model})"
