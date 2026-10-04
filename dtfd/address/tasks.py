import logging

import httpx
from celery import shared_task

from .geocoding import geocode
from .models import Address

logger = logging.getLogger(__name__)


@shared_task
def geocode_address(address_id: int) -> bool:
    """Preenche latitude/longitude do endereço via Nominatim."""
    address = Address.objects.filter(pk=address_id).first()
    if address is None:
        return False
    try:
        coords = geocode(address)
    except httpx.HTTPError:
        logger.warning("Nominatim falhou para o endereço %s", address_id, exc_info=True)
        return False
    if coords is None:
        return False
    Address.objects.filter(pk=address_id).update(latitude=coords[0], longitude=coords[1])
    return True
