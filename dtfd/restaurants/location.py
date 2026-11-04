"""Filtro de proximidade em km, aplicado antes de ordenar/paginar."""
import math

from django.contrib.contenttypes.models import ContentType
from django.db.models import FloatField, OuterRef, Subquery, Value
from django.db.models.functions import ACos, Cos, Sin, Radians, Least, Greatest, Cast
from rest_framework.exceptions import ValidationError

from address.models import Address
from .models import Restaurant


def apply_location(qs, params):
    lat, lon, radius = (params.get(k) for k in ('lat', 'lon', 'radius_km'))
    if lat in (None, '') and lon in (None, '') and radius in (None, ''):
        return qs
    try:
        if isinstance(lat, bool) or isinstance(lon, bool) or isinstance(radius, bool):
            raise ValueError
        lat, lon, radius = float(lat), float(lon), float(10 if radius in (None, '') else radius)
        if not all(math.isfinite(v) for v in (lat, lon, radius)) or not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 < radius <= 100):
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError({'location': 'Informe latitude, longitude e raio entre 0 e 100 km (exclusive 0).'})
    addresses = Address.objects.filter(content_type=ContentType.objects.get_for_model(Restaurant), object_id=OuterRef('pk'), latitude__isnull=False, longitude__isnull=False).order_by('-is_default', 'id')
    qs = qs.annotate(_latitude=Cast(Subquery(addresses.values('latitude')[:1]), FloatField()), _longitude=Cast(Subquery(addresses.values('longitude')[:1]), FloatField()))
    cosine = Sin(Radians(Value(lat))) * Sin(Radians('_latitude')) + Cos(Radians(Value(lat))) * Cos(Radians('_latitude')) * Cos(Radians('_longitude') - Radians(Value(lon)))
    return qs.annotate(distance_km=Value(6371.0088) * ACos(Least(Value(1.0), Greatest(Value(-1.0), cosine)))).filter(_latitude__isnull=False, _longitude__isnull=False, distance_km__lte=radius)
