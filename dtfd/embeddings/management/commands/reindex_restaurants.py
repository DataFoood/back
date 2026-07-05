from django.core.management.base import BaseCommand

from embeddings.services import reindex_all


class Command(BaseCommand):
    help = "Gera/atualiza embeddings dos restaurantes (cron). Default: só os stale."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true",
            help="Reindexa TODOS os restaurantes, não só os marcados como stale.",
        )

    def handle(self, *args, **options):
        only_stale = not options["all"]
        count = reindex_all(only_stale=only_stale)
        scope = "stale" if only_stale else "todos"
        self.stdout.write(self.style.SUCCESS(f"Reindexados {count} restaurante(s) ({scope})."))
