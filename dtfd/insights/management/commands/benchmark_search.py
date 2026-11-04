import json
import math
from time import perf_counter
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken
from users.models import User


class Command(BaseCommand):
    help = 'Mede buscas na instalação atual (até 20 requisições); não calibra capacidade automaticamente.'

    def add_arguments(self, parser):
        parser.add_argument('--user-email', required=True)
        parser.add_argument('--samples', type=int, default=10)

    def handle(self, *args, **options):
        if not 1 <= options['samples'] <= 20:
            raise CommandError('Use de 1 a 20 amostras, respeitando o throttle de busca.')
        user = User.objects.filter(email=options['user_email'], is_active=True).first()
        if user is None:
            raise CommandError('Conta ativa não encontrada. Use uma conta controlada para o benchmark.')
        allowed_host = next((host for host in settings.ALLOWED_HOSTS if host != '*'), 'localhost').lstrip('.')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        timings, modes = [], {}
        queries = ['pizza', 'café', 'almoço no centro', 'jantar tranquilo']
        for i in range(options['samples']):
            begin = perf_counter()
            response = client.post('/api/search/', {'query': queries[i % len(queries)], 'limit': 3}, format='json', HTTP_HOST=allowed_host)
            if response.status_code != 200:
                raise CommandError(f'Busca respondeu {response.status_code}; interrompendo o benchmark.')
            timings.append(round((perf_counter()-begin)*1000, 2))
            mode = response.json().get('mode', 'unknown')
            modes[mode] = modes.get(mode, 0)+1
        ordered = sorted(timings)
        self.stdout.write(json.dumps({'samples': len(ordered), 'p50_ms': ordered[math.ceil(len(ordered)*.5)-1],
            'p95_ms': ordered[math.ceil(len(ordered)*.95)-1], 'modes': modes, 'embedding_model': settings.EMBEDDING_MODEL,
            'development': settings.DEBUG, 'notice': 'Resultado desta instalação/modelo, sem teste de concorrência. Simuladores não calibram capacidade de produção.'}))
