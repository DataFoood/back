import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from restaurants.catalog import tourism


class Command(BaseCommand):
    help = 'Carrega os snapshots públicos reais de Marília (OSM + Turismo), sem rede e sem contas demo.'

    def handle(self, *args, **options):
        root = Path(__file__).resolve().parents[4] / 'catalog'
        try:
            payload = json.loads((root / 'marilia-tourism.json').read_text())
            records = payload['records']
            if payload.get('provider') != 'marilia_tourism' or not isinstance(records, list) or len(records) > 500:
                raise ValueError('Snapshot inválido.')
            fetched_at = parse_datetime(payload['fetched_at'])
            if fetched_at is None or fetched_at.tzinfo is None:
                raise ValueError('Data de consulta inválida.')
            for record in records:
                tourism.validate_record(record)
        except (OSError, KeyError, ValueError, TypeError) as error:
            raise CommandError('Snapshot turístico ausente ou inválido. Consulte catalog/README.md.') from error
        call_command('import_osm', file=root / 'marilia-osm.json', stdout=self.stdout)
        counts = {'created': 0, 'updated': 0, 'removed': 0}
        for record in records:
            counts[tourism.upsert(record, fetched_at)] += 1
        self.stdout.write('Turismo: ' + json.dumps(counts))
