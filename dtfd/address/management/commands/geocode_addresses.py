from django.core.management.base import BaseCommand

from address.models import Address
from address.tasks import geocode_address


class Command(BaseCommand):
    help = "Geocodifica (Nominatim) os endereços de restaurante sem coordenada. 1 req/s."

    def handle(self, *args, **options):
        pending = Address.objects.filter(
            content_type__model="restaurant", latitude__isnull=True
        ).values_list("pk", flat=True)
        done = sum(geocode_address(pk) for pk in pending)
        self.stdout.write(self.style.SUCCESS(f"Geocodificados {done} de {len(pending)} endereço(s)."))
