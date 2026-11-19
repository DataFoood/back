"""Ensaia uma instrução curta sem alterar o prompt dos processos web."""
import os
import sys

sys.path.insert(0, "/app/dtfd")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtfd.settings")

import django

django.setup()

from chats import recommendations
from django.core.management import call_command


send = recommendations.complete_chat


def short_instruction(messages, **options):
    return send([
        {"role": "system", "content": (
            "Ajude o cliente a escolher onde comer. Sugira em português um dos "
            "restaurantes cadastrados, citando o nome exatamente como foi fornecido. "
            "Use somente fatos dos dados. Escreva até duas frases."
        )},
        *messages[1:],
    ], **options)


recommendations.complete_chat = short_instruction
call_command("probe_chat")
