from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import GeoCell, PlatformDailyStat, RegionVisit, RestaurantDailyStat
from .tasks import label_cell

CELL = Decimal("0.01")  # ~1,1 km


def bump_restaurants(restaurant_ids, field: str) -> None:
    """+1 em `field` no dia de hoje pra cada restaurante. 2 queries, sem corrida."""
    if not restaurant_ids:
        return
    today = timezone.localdate()
    RestaurantDailyStat.objects.bulk_create(
        [RestaurantDailyStat(restaurant_id=rid, date=today) for rid in restaurant_ids],
        ignore_conflicts=True,
    )
    RestaurantDailyStat.objects.filter(restaurant_id__in=restaurant_ids, date=today).update(
        **{field: F(field) + 1}
    )


def bump_platform(field: str) -> None:
    today = timezone.localdate()
    PlatformDailyStat.objects.get_or_create(date=today)
    PlatformDailyStat.objects.filter(date=today).update(**{field: F(field) + 1})


def record_region_visit(restaurant_id: int, lat: float, lon: float) -> None:
    """Conta a visita na célula de ~1 km do visitante. A coordenada exata não é guardada."""
    cell, created = GeoCell.objects.get_or_create(
        lat=Decimal(str(lat)).quantize(CELL), lon=Decimal(str(lon)).quantize(CELL)
    )
    if created:
        transaction.on_commit(lambda: label_cell.delay(cell.pk))
    today = timezone.localdate()
    RegionVisit.objects.get_or_create(restaurant_id=restaurant_id, cell=cell, date=today)
    RegionVisit.objects.filter(restaurant_id=restaurant_id, cell=cell, date=today).update(
        count=F("count") + 1
    )
