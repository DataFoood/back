"""Vínculo de conta com o bot do Telegram.

Long polling (getUpdates) em vez de webhook: a aplicação roda local, sem
URL pública. O Celery beat chama `poll()` a cada poucos segundos; cada update
é processado uma vez (offset guardado no cache)."""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import messengers
from .models import MessagingPreference

logger = logging.getLogger(__name__)

LINK_TTL = timedelta(minutes=15)
OFFSET_KEY = "promotions:telegram:offset"
LOCK_KEY = "promotions:telegram:poll-lock"


def link_url(pref: MessagingPreference) -> tuple[str, str]:
    """Gera token de uso único -> deep link t.me/<bot>?start=<token>."""
    pref.telegram_link_token = secrets.token_urlsafe(24)  # [A-Za-z0-9_-], ≤ 64
    pref.telegram_link_expires_at = timezone.now() + LINK_TTL
    pref.save(update_fields=["telegram_link_token", "telegram_link_expires_at", "updated_at"])
    url = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={pref.telegram_link_token}"
    return url, pref.telegram_link_expires_at.isoformat()


def _reply(chat_id, text):
    try:
        messengers.telegram_call("sendMessage", {"chat_id": chat_id, "text": text})
    except messengers.DeliveryError:
        logger.info("telegram: não consegui responder ao chat")


def handle_update(update: dict) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    # só conversa privada: vincular um grupo mandaria promoção pra todo mundo dele
    if chat.get("type") != "private" or not chat.get("id") or not text:
        return
    chat_id = str(chat["id"])
    command, _, arg = text.partition(" ")
    command = command.split("@")[0].lower()

    if command == "/start":
        token = arg.strip()
        pref = None
        if token:
            pref = MessagingPreference.objects.filter(
                telegram_link_token=token, telegram_link_expires_at__gt=timezone.now()
            ).first()
        if pref is None:
            _reply(chat_id, "Link inválido ou expirado. Gere um novo em Perfil > Promoções no DataFood.")
            return
        # um chat = uma conta: se este Telegram estava em outra conta, sai de lá
        MessagingPreference.objects.filter(telegram_chat_id=chat_id).exclude(pk=pref.pk).update(
            telegram_chat_id="", telegram_linked_at=None
        )
        pref.telegram_chat_id = chat_id
        pref.telegram_linked_at = timezone.now()
        pref.telegram_link_token = ""
        pref.telegram_link_expires_at = None
        pref.save()
        _reply(
            chat_id,
            "Pronto! Você vai receber aqui as promoções dos restaurantes que salvou no DataFood. "
            "Envie /sair para parar.",
        )
    elif command in ("/sair", "/stop"):
        MessagingPreference.objects.filter(telegram_chat_id=chat_id).update(
            telegram_chat_id="", telegram_linked_at=None
        )
        _reply(chat_id, "Feito. Você não vai mais receber promoções por aqui.")


def poll() -> int:
    """Processa os updates pendentes. Retorna quantos processou."""
    if not messengers.telegram_enabled():
        return 0
    # beat a cada 10s + chamada lenta = sobreposição; o lock evita processar 2x
    if not cache.add(LOCK_KEY, 1, timeout=60):
        return 0
    try:
        offset = cache.get(OFFSET_KEY)
        payload = {"timeout": 0, "allowed_updates": ["message"]}
        if offset:
            payload["offset"] = offset
        try:
            updates = messengers.telegram_call("getUpdates", payload).get("result", [])
        except messengers.DeliveryError:
            logger.warning("telegram: getUpdates falhou", exc_info=True)
            return 0
        for update in updates:
            try:
                handle_update(update)
            except Exception:
                logger.exception("telegram: update %s falhou", update.get("update_id"))
            cache.set(OFFSET_KEY, update["update_id"] + 1, timeout=None)
        return len(updates)
    finally:
        cache.delete(LOCK_KEY)
