from celery import shared_task

from restaurants.models import Restaurant

from .services import reindex_all, reindex_restaurant


@shared_task
def reindex_stale() -> int:
    """Reindexa só os restaurantes marcados como stale (cron horário)."""
    return reindex_all(only_stale=True)


@shared_task
def reindex_all_task() -> int:
    """Reindexa TODOS (ex: troca de modelo de embedding)."""
    return reindex_all(only_stale=False)


@shared_task
def reindex_one(restaurant_id: int) -> bool:
    """Reindexa um restaurante específico."""
    restaurant = Restaurant.objects.filter(pk=restaurant_id).first()
    if restaurant is None:
        return False
    reindex_restaurant(restaurant)
    return True
