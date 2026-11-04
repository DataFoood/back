from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from insights.models import AnalyticsEvent, AnalyticsDaily
from promotions.models import PromotionReservation, PromotionOutbox, PromotionDelivery


class Command(BaseCommand):
    help = 'Reconstrói agregados e aplica retenção de 180 dias aos eventos operacionais.'

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        cutoff = now - timedelta(days=180)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [314159265])
        AnalyticsEvent.objects.filter(created_at__lt=cutoff).delete()
        rows = AnalyticsEvent.objects.annotate(day=TruncDate('created_at')).values('restaurant_id', 'day', 'kind').annotate(n=Count('id'))
        aggregates = [AnalyticsDaily(restaurant_id=r['restaurant_id'], day=r['day'], kind=r['kind'], count=r['n']) for r in rows]
        AnalyticsDaily.objects.all().delete()
        AnalyticsDaily.objects.bulk_create(aggregates, batch_size=1000)
        PromotionReservation.objects.filter(expires_at__lt=now).delete()
        PromotionOutbox.objects.exclude(promotion__status='sending').delete()
        PromotionDelivery.objects.filter(created_at__lt=cutoff).exclude(status__in=['pending', 'sending']).delete()
        self.stdout.write(f'{len(aggregates)} agregados atualizados; retenção de 180 dias aplicada.')
