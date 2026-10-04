"""Acessos FICTÍCIOS pra demonstrar o BI/mapa do dono (só em DEBUG).

Distribui visitas e aparições na busca dos últimos N dias em células de ~1 km
ao redor de cada restaurante geocodificado, com pico no almoço/jantar e no
fim de semana. Determinístico (--seed)."""

import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from address.models import Address
from analytics.models import AccessStat, GeoCell
from analytics.services import CELL

HOUR_WEIGHT = [1, 1, 0, 0, 0, 0, 1, 2, 3, 3, 4, 9, 12, 10, 5, 3, 3, 5, 9, 12, 11, 8, 4, 2]
AGE_WEIGHT = {"unknown": 45, "18-24": 14, "25-39": 20, "40-59": 14, "60+": 6, "lt18": 1}


class Command(BaseCommand):
    help = "Gera acessos fictícios (dados de demonstração) pro mapa de calor do dono. Só com DEBUG=True."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clear", action="store_true", help="Apaga todos os AccessStat antes.")

    def handle(self, *args, days, seed, clear, **options):
        if not settings.DEBUG:
            raise CommandError("Dados fictícios só em DEBUG — não polua métricas reais.")
        rnd = random.Random(seed)
        if clear:
            AccessStat.objects.all().delete()

        places = list(
            Address.objects.filter(content_type__model="restaurant", latitude__isnull=False)
            .values_list("object_id", "latitude", "longitude", "neighborhood", "city")
        )
        if not places:
            raise CommandError("Nenhum restaurante geocodificado. Rode geocode_addresses antes.")

        def nearest_hood(lat, lon):
            """Bairro do restaurante geocodificado mais perto da célula."""
            _, _, _, hood, city = min(places, key=lambda p: (p[1] - lat) ** 2 + (p[2] - lon) ** 2)
            return f"{hood}, {city}"

        today = timezone.localdate()
        cells: dict[tuple, GeoCell] = {}
        rows: dict[tuple, int] = {}
        for rid, lat, lon, _hood, _city in places:
            popularity = rnd.uniform(0.6, 1.6)
            for d in range(days):
                day = today - timedelta(days=d)
                weekend = 1.8 if day.weekday() >= 4 else 1.0  # sexta a domingo
                for hour, hw in enumerate(HOUR_WEIGHT):
                    expected = hw * weekend * popularity * 0.35
                    for _ in range(int(rnd.expovariate(1 / expected)) if expected else 0):
                        # quem busca está a até ~4 km; poucos vêm de longe
                        spread = 0.04 if rnd.random() < 0.85 else 0.12
                        clat = (lat + Decimal(str(rnd.gauss(0, spread / 2)))).quantize(CELL)
                        clon = (lon + Decimal(str(rnd.gauss(0, spread / 2)))).quantize(CELL)
                        cell = cells.get((clat, clon))
                        if cell is None:
                            cell, _ = GeoCell.objects.get_or_create(lat=clat, lon=clon)
                            if not cell.label:  # nome real (reverse geocoding) não é sobrescrito
                                cell.label = nearest_hood(clat, clon)
                                cell.save(update_fields=["label"])
                            cells[(clat, clon)] = cell
                        located = rnd.random() < 0.7
                        age = rnd.choices(list(AGE_WEIGHT), weights=list(AGE_WEIGHT.values()))[0]
                        events = [AccessStat.Event.IMPRESSION] * 3
                        events.append(AccessStat.Event.SEARCH_VIEW if rnd.random() < 0.6 else AccessStat.Event.VIEW)
                        for event in events:
                            key = (rid, day, hour, event, age, cell.pk if located else None)
                            rows[key] = rows.get(key, 0) + 1

        AccessStat.objects.bulk_create(
            [AccessStat(restaurant_id=r, date=d, hour=h, event=e, age=a, cell_id=c, count=n)
             for (r, d, h, e, a, c), n in rows.items()],
            update_conflicts=True,
            unique_fields=["restaurant", "date", "hour", "event", "age", "cell"],
            update_fields=["count"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"{sum(rows.values())} acessos fictícios em {len(rows)} linhas, {len(places)} restaurante(s), {days} dias."
        ))
