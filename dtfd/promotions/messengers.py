"""Clientes dos mensageiros. Isolados para serem mockáveis nos testes.

Telegram: Bot API por HTTPS de saída (funciona numa máquina local sem IP
público — o vínculo chega por long polling, ver telegram.py).
E-mail: backend do Django (console em dev, SMTP via env).
WhatsApp: sem API — o dono compartilha um link wa.me (ver services.whatsapp_url).
"""

import smtplib

import httpx
from django.conf import settings
from django.core.mail import EmailMessage


class DeliveryError(Exception):
    """Falha de envio (registrada na entrega, não derruba o lote)."""


class RecipientGone(DeliveryError):
    """O destinatário não existe mais no canal (ex.: bloqueou o bot)."""


class TransientDeliveryError(DeliveryError):
    retry_after = 0


class UnknownDeliveryError(DeliveryError):
    """Pode ter sido aceito: não repetir automaticamente."""


class _RateLimited(TransientDeliveryError):
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
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        raise TransientDeliveryError("Telegram indisponível antes da conexão.") from exc
    except httpx.HTTPError as exc:
        raise UnknownDeliveryError("Não foi possível confirmar a aceitação pelo Telegram.") from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code == 403:
        raise RecipientGone(data.get("description") or "bot bloqueado pelo usuário")
    if response.status_code == 429:
        retry_after = (data.get("parameters") or {}).get("retry_after", 1)
        raise _RateLimited(retry_after)
    if response.status_code >= 500:
        raise TransientDeliveryError(f"Telegram respondeu {response.status_code}.")
    if not data.get("ok"):
        raise DeliveryError(data.get("description") or f"telegram respondeu {response.status_code}")
    return data


def send_telegram(chat_id: str, text: str) -> None:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
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
        if message.send(fail_silently=False) != 1:
            raise DeliveryError("O backend não aceitou o e-mail.")
    except DeliveryError:
        raise
    except smtplib.SMTPResponseException as exc:
        error_type = TransientDeliveryError if 400 <= exc.smtp_code < 500 else DeliveryError
        raise error_type(f"SMTP respondeu {exc.smtp_code}.") from exc
    except (smtplib.SMTPServerDisconnected, TimeoutError) as exc:
        raise UnknownDeliveryError("Não foi possível confirmar a aceitação pelo SMTP.") from exc
    except ConnectionError as exc:
        raise TransientDeliveryError("Não foi possível conectar ao SMTP.") from exc
    except Exception as exc:  # SMTP levanta vários tipos
        raise DeliveryError(f"e-mail falhou: {exc.__class__.__name__}") from exc
