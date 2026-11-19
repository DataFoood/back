import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chats.recommendations import compose_reply, interpret_turn, select_restaurants, taxonomy_choices


class Command(BaseCommand):
    help = "Mede o chat real com o catálogo de Marília, sem gravar conversas ou contas."

    def handle(self, *args, **options):
        if not settings.CHAT_GENERATION_ENABLED:
            raise CommandError("Geração desabilitada; o modelo não foi testado.")
        filters, history, choices = {}, [], taxonomy_choices()
        for query in ("Quero jantar em Marília", "Quero pizza", "E que seja em um lugar aberto"):
            start = time.perf_counter()
            turn = interpret_turn(query, filters, choices)
            if turn is None or not turn.ready:
                raise CommandError("Pedido não reconhecido; conferir o catálogo de Marília antes do ensaio.")
            filters.update(turn.filters.model_dump(exclude_none=True))
            for key in turn.remove_filters:
                filters.pop(key, None)
            ids, limited = select_restaurants(filters, {})
            answer = compose_reply(query, history, filters, choices, {}, ids) if ids else "Nenhum cadastro com esses filtros."
            self.stdout.write(json.dumps({
                "query": query, "filters": filters, "recommendations": len(ids), "limited": limited,
                "answer": answer, "seconds": round(time.perf_counter() - start, 2),
            }, ensure_ascii=False))
            self.stdout.flush()
            if ids and answer is None:
                raise CommandError("O modelo não escreveu uma resposta válida; conferir logs/recursos antes de aprovar.")
            history.extend([{"role": "user", "text": query}, {"role": "assistant", "content": {"answer": answer}}])
