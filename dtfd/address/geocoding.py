"""Geocoding via Nominatim (OpenStreetMap): endereço -> coordenada e
coordenada -> nome da região. Só endereço de restaurante (público) vai pra lá."""

import time
from decimal import Decimal

import httpx
from django.conf import settings
from django.core.cache import cache

SIX_PLACES = Decimal("0.000001")


def _get(path: str, params: dict) -> dict | list:
    # ponytail: trava global de 1 req/s via cache (Redis), vale pra todos os
    # workers; fila dedicada se o volume crescer
    while not cache.add("nominatim-lock", 1, timeout=1):
        time.sleep(0.2)
    response = httpx.get(
        f"{settings.NOMINATIM_URL}/{path}",
        params={**params, "format": "jsonv2"},
        headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def geocode(address) -> tuple[Decimal, Decimal] | None:
    """(lat, lon) do endereço; cai pro centro da cidade se a rua não for achada."""
    place = {"city": address.city, "state": address.state, "country": address.country, "limit": 1}
    street = f"{address.number} {address.street}".strip()
    hits = _get("search", {**place, "street": street}) if street else []
    if not hits:
        hits = _get("search", place)
    if not hits:
        return None
    return (
        Decimal(hits[0]["lat"]).quantize(SIX_PLACES),
        Decimal(hits[0]["lon"]).quantize(SIX_PLACES),
    )


def region_label(lat: float, lon: float) -> str:
    """Nome legível da região (bairro, cidade) de uma coordenada."""
    data = _get("reverse", {"lat": lat, "lon": lon, "zoom": 14})
    parts = data.get("address", {}) if isinstance(data, dict) else {}
    area = parts.get("suburb") or parts.get("neighbourhood") or parts.get("city_district")
    city = parts.get("city") or parts.get("town") or parts.get("village")
    return ", ".join(p for p in (area, city) if p) or f"{lat:.2f}, {lon:.2f}"
