import json
from pathlib import Path

import httpx
from django.db import transaction
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from restaurants.catalog import osm
from restaurants.models import CatalogImport, Restaurant, RestaurantSource
from promotions.models import Promotion


class Command(BaseCommand):
    help = 'Importa restaurantes do OpenStreetMap em Marília/SP (IBGE 3529005).'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=Path, help='Resposta Overpass local para importação/reprocessamento.')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--replace', action='store_true', help='Arquiva o catálogo anterior após importar o arquivo validado; preserva contas e registros relacionados.')

    def handle(self, *args, **options):
        run = CatalogImport.objects.create(region_code=osm.REGION_CODE)
        counts = dict(created=0, updated=0, removed=0, skipped=0, valid=0, archived=0, archived_promotions=0)
        try:
            path = options['file']
            if options['replace'] and not path:
                raise ValueError('--replace exige --file para usar um lote revisável.')
            if path and path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('Arquivo maior que 32 MiB.')
            payload = json.loads(path.read_text(encoding='utf-8')) if path else osm.fetch()
            if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list) or payload.get('remark'):
                raise ValueError('Resposta Overpass inválida ou parcial.')
            if len(payload['elements']) > 10000:
                raise ValueError('Importação limitada a 10 mil objetos por execução.')
            # Validar toda a resposta antes de começar a gravar objetos.
            records = [osm.normalize(e) for e in payload['elements']]
            counts['valid'] = sum(record is not None for record in records)
            counts['skipped'] = len(records) - counts['valid']
            if options['replace'] and not counts['valid']:
                raise ValueError('Lote sem estabelecimentos válidos; catálogo preservado.')
            external_ids = [record['external_id'] for record in records if record]
            # Importação e arquivamento juntos: uma falha preserva o catálogo inteiro.
            with transaction.atomic():
                if not options['dry_run']:
                    for record in records:
                        if record:
                            counts[osm.upsert(record)] += 1
                if options['replace']:
                    selected = RestaurantSource.objects.filter(provider='osm', external_id__in=external_ids).values_list('restaurant_id', flat=True)
                    if not options['dry_run'] and not Restaurant.objects.filter(pk__in=selected).exists():
                        raise ValueError('Nenhum restaurante ativo importado; catálogo preservado.')
                    old = Restaurant.objects.exclude(pk__in=selected)
                    promotions = Promotion.objects.filter(restaurant__in=old)
                    counts['archived_promotions'] = promotions.count() if options['dry_run'] else promotions.update(deleted_at=timezone.now(), updated_at=timezone.now())
                    counts['archived'] = old.count() if options['dry_run'] else old.update(deleted_at=timezone.now(), updated_at=timezone.now())
            run.status = 'preview' if options['dry_run'] else 'completed'
        except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
            run.status = 'failed'
            run.error = type(exc).__name__  # sem URLs de proxy ou conteúdo de credenciais
            raise CommandError(f'Importação falhou ({type(exc).__name__}); nenhum dado foi inventado.') from exc
        finally:
            run.finished_at, run.counts = timezone.now(), counts
            run.save()
        self.stdout.write(json.dumps(counts))
