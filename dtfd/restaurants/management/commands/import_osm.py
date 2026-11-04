import json
from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from restaurants.catalog import osm
from restaurants.models import CatalogImport


class Command(BaseCommand):
    help = 'Importa restaurantes do OpenStreetMap em Marília/SP (IBGE 3529005).'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=Path, help='Resposta Overpass local para importação/reprocessamento.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        run = CatalogImport.objects.create(region_code=osm.REGION_CODE)
        counts = dict(created=0, updated=0, removed=0, skipped=0, valid=0)
        try:
            path = options['file']
            if path and path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('Arquivo maior que 32 MiB.')
            payload = json.loads(path.read_text()) if path else osm.fetch()
            if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list) or payload.get('remark'):
                raise ValueError('Resposta Overpass inválida ou parcial.')
            if len(payload['elements']) > 10000:
                raise ValueError('Importação limitada a 10 mil objetos por execução.')
            # Validar toda a resposta antes de começar a gravar objetos.
            records = [osm.normalize(e) for e in payload['elements']]
            for record in records:
                if record is None:
                    counts['skipped'] += 1
                    continue
                counts['valid'] += 1
                if not options['dry_run']:
                    counts[osm.upsert(record)] += 1
            run.status = 'preview' if options['dry_run'] else 'completed'
        except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
            run.status = 'failed'
            run.error = type(exc).__name__  # sem URLs de proxy ou conteúdo de credenciais
            raise CommandError(f'Importação falhou ({type(exc).__name__}); nenhum dado foi inventado.') from exc
        finally:
            run.finished_at, run.counts = timezone.now(), counts
            run.save()
        self.stdout.write(json.dumps(counts))
