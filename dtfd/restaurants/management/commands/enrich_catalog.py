import hashlib
import socket
from urllib.parse import urlparse

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from restaurants.catalog.websites import fetch_metadata, image_url
from restaurants.models import Restaurant, RestaurantImage, RestaurantSource


class Command(BaseCommand):
    help = 'Enriquece cadastros OSM sem dono usando metadados de sites públicos autorizados.'

    def add_arguments(self, parser):
        parser.add_argument('--allow-host', action='append', required=True, help='Hostname exato autorizado (repita para www/redirecionamento).')
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 100:
            raise CommandError('Limit deve ser entre 1 e 100.')
        allowed = set(options['allow_host'])
        count = 0
        candidates = Restaurant.objects.filter(origin='osm', owner__isnull=True).exclude(website='').order_by('pk')
        for restaurant in candidates:
            url = restaurant.website
            if urlparse(url).hostname not in allowed:
                continue
            if count >= options['limit']:
                break
            count += 1
            # Muitos links OSM antigos ainda usam HTTP, mas só consultamos HTTPS.
            url = 'https://' + url.split('://', 1)[-1]
            try:
                page, meta = fetch_metadata(url, allowed)
                image = image_url(meta.get('og:image', ''), page) if meta.get('og:image') else ''
                description = meta.get('og:description', meta.get('description', '')).strip()[:2000]
                if options['dry_run']:
                    self.stdout.write(f'{restaurant.pk}: imagem={bool(image)}, descrição={bool(description)} (prévia)')
                    continue
                with transaction.atomic():
                    # O dono pode ter assumido o cadastro durante o request.
                    locked = Restaurant.objects.select_for_update().get(pk=restaurant.pk)
                    if locked.owner_id is not None:
                        continue
                    attribution = f'Site do estabelecimento: {urlparse(page).hostname}'
                    RestaurantSource.objects.update_or_create(provider='website', external_id=str(restaurant.pk) + ':' + hashlib.sha256(page.encode()).hexdigest()[:32],
                        defaults={'restaurant': locked, 'url': page[:200], 'attribution': attribution,
                                  'license': '', 'fetched_at': timezone.now(), 'data': {'metadata': meta}})
                    if description:
                        locked.description = description
                    if image:
                        RestaurantImage.objects.get_or_create(restaurant=locked, url=image, defaults={'source_url': page[:200], 'attribution': attribution})
                        if not locked.cover_image:
                            locked.cover_image = image
                    locked.save()
                self.stdout.write(f'{restaurant.pk}: imagem={bool(image)}, descrição={bool(description)}')
            except (httpx.HTTPError, ValueError, OSError, socket.gaierror):
                self.stderr.write(f'{restaurant.pk}: site indisponível ou não autorizado; cadastro preservado.')
