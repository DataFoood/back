from celery import shared_task
from django.contrib.auth import get_user_model

from .services import compute_user_preferences

User = get_user_model()


@shared_task
def recompute_all() -> int:
    """Recalcula afinidades de todos os usuários (cron diário)."""
    count = 0
    for user in User.objects.all():
        compute_user_preferences(user)
        count += 1
    return count
