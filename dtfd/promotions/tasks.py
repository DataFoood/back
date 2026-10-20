from celery import shared_task

from . import services, telegram


@shared_task
def send_promotion(promotion_id: int) -> dict:
    """Envia uma promoção já marcada como 'enviando'."""
    return services.deliver(promotion_id)


@shared_task
def dispatch_scheduled() -> int:
    """Cron de minuto: dispara as agendadas que venceram (e retoma travadas)."""
    pks = services.claim_due()
    for pk in pks:
        send_promotion.delay(pk)
    return len(pks)


@shared_task
def poll_telegram() -> int:
    """Vínculos e /sair do bot (long polling; app local não tem webhook)."""
    return telegram.poll()
