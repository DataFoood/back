import httpx
from celery import shared_task

from address.geocoding import region_label

from .models import GeoCell


@shared_task
def label_cell(cell_id: int) -> bool:
    """Nomeia a célula (bairro, cidade) via reverse geocoding."""
    cell = GeoCell.objects.filter(pk=cell_id, label="").first()
    if cell is None:
        return False
    try:
        label = region_label(float(cell.lat), float(cell.lon))
    except httpx.HTTPError:
        return False  # fica sem nome; o painel mostra a coordenada
    GeoCell.objects.filter(pk=cell_id).update(label=label[:200])
    return True
