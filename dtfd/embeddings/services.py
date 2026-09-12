import logging

from django.conf import settings

from restaurants.models import Restaurant

from .documents import build_restaurant_document
from .models import RestaurantEmbedding
from .ollama import embed_text

logger = logging.getLogger(__name__)


def reindex_restaurant(restaurant: Restaurant) -> RestaurantEmbedding:
    """(Re)gera o embedding de um restaurante e reseta o flag stale."""
    document = build_restaurant_document(restaurant)
    vector = embed_text(document)
    embedding, _ = RestaurantEmbedding.objects.update_or_create(
        restaurant=restaurant,
        defaults={
            "embedding": vector,
            "document": document,
            "model": settings.EMBEDDING_MODEL,
        },
    )
    Restaurant.objects.filter(pk=restaurant.pk).update(embedding_stale=False)
    return embedding


def reindex_all(only_stale: bool = True) -> int:
    """Reindexa restaurantes. only_stale=True processa só os marcados;
    False refaz todos. Retorna a quantidade processada."""
    qs = Restaurant.objects.all()
    if only_stale:
        qs = qs.filter(embedding_stale=True)
    count = 0
    for restaurant in qs:
        # isola falha por restaurante: um erro (Ollama timeout, etc) não
        # aborta a rodada inteira do cron.
        try:
            reindex_restaurant(restaurant)
            count += 1
        except Exception:
            logger.exception("Falha ao reindexar restaurante %s", restaurant.pk)
            continue
    return count
