"""Histograma operacional agregado, sem consultas, IP ou identidade."""
import logging
from time import perf_counter
from django.db.models import F
from django.utils import timezone
from .models import OperationalBucket

logger = logging.getLogger(__name__)


class OperationalMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = perf_counter()
        response = self.get_response(request)
        if request.path != '/api/search/' or request.method != 'POST':
            return response
        elapsed = max(0, round((perf_counter()-started)*1000))
        bucket = 'over3000'
        for bound in (100, 500, 1000, 3000):
            if elapsed <= bound:
                bucket = f'le{bound}'
                break
        try:
            minute = timezone.now().replace(second=0, microsecond=0)
            row, _ = OperationalBucket.objects.get_or_create(minute=minute, component='search')
            OperationalBucket.objects.filter(pk=row.pk).update(count=F('count')+1,
                errors=F('errors')+int(response.status_code >= 500), duration_ms=F('duration_ms')+elapsed,
                **{bucket: F(bucket)+1})
        except Exception as exc:
            # Coleta não pode transformar indisponibilidade de métricas em
            # falha da aplicação, nem vazar payloads/autenticação em logs.
            logger.warning('Métrica operacional não persistida (%s).', type(exc).__name__)
        return response
