"""Sugestão de contratar infraestrutura no fim de semana.

A aplicação roda local (docker compose numa máquina). O fim de semana é o
pico de restaurante: mais buscas e mais promoções. Aqui projetamos a carga do
próximo fim de semana a partir das últimas 4 semanas + promoções já agendadas
e comparamos com a capacidade local configurada. Passou do limite, sugerimos
subir a stack de produção (docs/deploy.md) só de sexta à noite a domingo."""

from collections import defaultdict
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import Count
from django.db.models.functions import ExtractIsoWeekDay
from django.utils import timezone

from preferences.models import SearchHistory

from .models import Promotion, PromotionDelivery
from .services import estimated_messages

HISTORY_WEEKS = 4
WEEKEND_DAYS = (4, 5, 6)  # sexta, sábado, domingo (0 = segunda)
ATTENTION_AT = 0.7
# janela sugerida: sexta 17h -> domingo 23h
WINDOW_START = (4, time(17, 0))
WINDOW_END = (6, time(23, 0))


def _per_weekday(qs, field, since, until):
    """Média por dia da semana (0=seg) no intervalo [since, until)."""
    rows = (
        qs.filter(**{f"{field}__gte": since, f"{field}__lt": until})
        .annotate(wd=ExtractIsoWeekDay(field))
        .values("wd")
        .annotate(n=Count("id"))
    )
    totals = {row["wd"] - 1: row["n"] for row in rows}
    return [totals.get(d, 0) / HISTORY_WEEKS for d in range(7)]


def _aware(day, at):
    return timezone.make_aware(datetime.combine(day, at))


def upcoming_weekend(today):
    """Sexta do fim de semana atual (se já é sex–dom) ou do próximo."""
    weekday = today.weekday()
    friday = today - timedelta(days=weekday - 4) if weekday >= 4 else today + timedelta(days=4 - weekday)
    return friday


def suggestion() -> dict:
    today = timezone.localdate()
    since = _aware(today - timedelta(weeks=HISTORY_WEEKS), time.min)
    until = _aware(today, time.min)

    messages = _per_weekday(
        PromotionDelivery.objects.filter(status=PromotionDelivery.Status.SENT),
        "sent_at", since, until,
    )
    searches = _per_weekday(SearchHistory.objects.all(), "created_at", since, until)

    friday = upcoming_weekend(today)
    weekend_start = _aware(friday, time.min)
    weekend_end = _aware(friday + timedelta(days=3), time.min)
    scheduled = Promotion.objects.filter(
        status=Promotion.Status.SCHEDULED,
        scheduled_for__gte=max(weekend_start, timezone.now()),
        scheduled_for__lt=weekend_end,
    ).select_related("restaurant")
    scheduled_by_day = defaultdict(int)
    scheduled_count = 0
    for promotion in scheduled:
        scheduled_count += 1
        day = timezone.localtime(promotion.scheduled_for).date()
        scheduled_by_day[day] += estimated_messages(promotion)

    hist_msgs_peak = max(messages[d] for d in WEEKEND_DAYS)
    hist_search_peak = max(searches[d] for d in WEEKEND_DAYS)
    # já agendado é carga certa; histórico cobre o que é disparado na hora
    projected_msgs = max(hist_msgs_peak, max(scheduled_by_day.values(), default=0))
    projected_searches = hist_search_peak

    cap_msgs = settings.LOCAL_CAPACITY_MESSAGES_PER_DAY
    cap_searches = settings.LOCAL_CAPACITY_SEARCHES_PER_DAY
    util_msgs = projected_msgs / cap_msgs if cap_msgs else 0
    util_searches = projected_searches / cap_searches if cap_searches else 0
    utilization = max(util_msgs, util_searches)

    weekday_msgs = sum(messages[:4]) / 4
    weekday_searches = sum(searches[:4]) / 4

    reasons = []
    if util_msgs >= ATTENTION_AT:
        reasons.append(
            f"promoções: pico previsto de {round(projected_msgs)} mensagens/dia "
            f"({round(util_msgs * 100)}% da capacidade local de {cap_msgs})."
        )
    if util_searches >= ATTENTION_AT:
        reasons.append(
            f"busca: pico previsto de {round(projected_searches)} buscas/dia "
            f"({round(util_searches * 100)}% da capacidade local de {cap_searches})."
        )
    if scheduled_count:
        reasons.append(f"{scheduled_count} promoção(ões) já agendada(s) para o fim de semana.")

    level = "hire" if utilization >= 1 else "attention" if utilization >= ATTENTION_AT else "ok"

    window_start = _aware(friday + timedelta(days=WINDOW_START[0] - 4), WINDOW_START[1])
    window_end = _aware(friday + timedelta(days=WINDOW_END[0] - 4), WINDOW_END[1])
    hours = round((window_end - window_start).total_seconds() / 3600)
    hourly = settings.WEEKEND_INFRA_HOURLY_COST

    return {
        "level": level,
        "recommend": level != "ok",
        "reasons": reasons,
        "weekend": {"start": weekend_start.isoformat(), "end": weekend_end.isoformat()},
        "projected": {
            "messages_peak_day": round(projected_msgs),
            "searches_peak_day": round(projected_searches),
        },
        "capacity": {"messages_per_day": cap_msgs, "searches_per_day": cap_searches},
        "utilization": round(utilization, 2),
        "weekday_baseline": {
            "messages_per_day": round(weekday_msgs, 1),
            "searches_per_day": round(weekday_searches, 1),
        },
        "history_by_weekday": [
            {"day_week": d, "messages": round(messages[d], 1), "searches": round(searches[d], 1)}
            for d in range(7)
        ],
        "scheduled": {
            "promotions": scheduled_count,
            "messages": sum(scheduled_by_day.values()),
        },
        "suggested_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "hours": hours,
        },
        "estimated_cost": {
            "currency": "BRL",
            "hourly": hourly,
            "total": round(hourly * hours, 2),
        },
        "history_weeks": HISTORY_WEEKS,
    }
