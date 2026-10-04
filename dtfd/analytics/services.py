import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import AccessStat, GeoCell, PlatformDailyStat
from .tasks import label_cell

CELL = Decimal("0.01")  # ~1,1 km
Age = AccessStat.Age


def age_bracket(user, today: datetime.date | None = None) -> str:
    """Faixa etária só de quem consentiu (LGPD) e informou a data de nascimento."""
    if not (user and user.is_authenticated and user.allow_info and user.birthday):
        return Age.UNKNOWN
    today = today or timezone.localdate()
    b = user.birthday
    years = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    if years < 18:
        return Age.UNDER_18
    if years < 25:
        return Age.AGE_18_24
    if years < 40:
        return Age.AGE_25_39
    if years < 60:
        return Age.AGE_40_59
    return Age.AGE_60_PLUS


def cell_for(coords: tuple[float, float] | None) -> GeoCell | None:
    """Célula de ~1 km da coordenada; a coordenada exata não é guardada."""
    if coords is None:
        return None
    lat, lon = (Decimal(str(v)).quantize(CELL) for v in coords)
    cell, created = GeoCell.objects.get_or_create(lat=lat, lon=lon)
    if created:
        transaction.on_commit(lambda: label_cell.delay(cell.pk))
    return cell


def record_access(restaurant_ids, event: str, *, user=None, coords=None) -> None:
    """+1 no acesso de cada restaurante na hora atual. 2 queries, sem corrida."""
    if not restaurant_ids:
        return
    now = timezone.localtime()
    key = {
        "date": now.date(), "hour": now.hour, "event": event,
        "age": age_bracket(user, now.date()), "cell": cell_for(coords),
    }
    AccessStat.objects.bulk_create(
        [AccessStat(restaurant_id=rid, **key) for rid in restaurant_ids], ignore_conflicts=True
    )
    AccessStat.objects.filter(restaurant_id__in=restaurant_ids, **key).update(count=F("count") + 1)


def bump_platform(field: str) -> None:
    today = timezone.localdate()
    PlatformDailyStat.objects.get_or_create(date=today)
    PlatformDailyStat.objects.filter(date=today).update(**{field: F(field) + 1})
