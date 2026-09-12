from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from preferences.services import compute_user_preferences

User = get_user_model()


class Command(BaseCommand):
    help = "Recalcula as afinidades (preferências) dos usuários a partir das interações."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", type=int, default=None,
            help="ID de um usuário específico. Sem isso, recalcula todos.",
        )

    def handle(self, *args, **options):
        user_id = options["user"]
        users = User.objects.filter(pk=user_id) if user_id else User.objects.all()
        total = 0
        for user in users:
            compute_user_preferences(user)
            total += 1
        self.stdout.write(self.style.SUCCESS(f"Recalculado para {total} usuário(s)."))
