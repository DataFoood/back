"""Clientes dos mensageiros. Isolados para serem mockáveis nos testes.

Telegram: Bot API por HTTPS de saída (funciona numa máquina local sem IP
público — o vínculo chega por long polling, ver telegram.py).
E-mail: backend do Django (console em dev, SMTP via env).
WhatsApp: sem API — o dono compartilha um link wa.me (ver services.whatsapp_url).
"""

import time

import httpx
from django.conf import settings
from django.core.mail import EmailMessage


class DeliveryError(Exception):
    """Falha de envio (registrada na entrega, não derruba o lote)."""


class RecipientGone(DeliveryError):
    """O destinatário não existe mais no canal (ex.: bloqueou o bot)."""


class _RateLimited(DeliveryError):
    def __init__(self, retry_after):
        super().__init__(f"telegram pediu pausa de {retry_after}s")
        self.retry_after = retry_after


def telegram_enabled() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def telegram_call(method: str, payload: dict, timeout: float = 15) -> dict:
    """Chama a Bot API. Levanta DeliveryError com a descrição do Telegram."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise DeliveryError(f"telegram inacessível: {exc.__class__.__name__}") from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code == 403:
        raise RecipientGone(data.get("description") or "bot bloqueado pelo usuário")
    if response.status_code == 429:
        retry_after = (data.get("parameters") or {}).get("retry_after", 1)
        raise _RateLimited(retry_after)
    if not data.get("ok"):
        raise DeliveryError(data.get("description") or f"telegram respondeu {response.status_code}")
    return data


def send_telegram(chat_id: str, text: str) -> None:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
    try:
        telegram_call("sendMessage", payload)
    except _RateLimited as exc:
        # uma nova tentativa respeitando o retry_after (limitado: não trava o worker)
        time.sleep(min(float(exc.retry_after), 30))
        telegram_call("sendMessage", payload)


def send_email(to: str, subject: str, body: str, unsubscribe_url: str) -> None:
    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        # clientes de e-mail mostram "cancelar inscrição" nativo
        headers={"List-Unsubscribe": f"<{unsubscribe_url}>"},
    )
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # SMTP levanta vários tipos
        raise DeliveryError(f"e-mail falhou: {exc.__class__.__name__}") from exc
