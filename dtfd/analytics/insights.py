"""Consultas do BI do dono sobre AccessStat. Só agregados; qualquer grupo com
1 a K-1 acessos sai como None ("menos de K") pra não expor uma pessoa."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from .models import AccessStat

K = 5
Event = AccessStat.Event
METRICS = {
    "views": [Event.VIEW, Event.SEARCH_VIEW],
    "impressions": [Event.IMPRESSION],
    "clicks": [Event.SEARCH_VIEW],
}


def mask(n: int) -> int | None:
    return n if n == 0 or n >= K else None


def restaurant_insights(restaurant, *, days=30, metric="views", ages=None, hour_from=0, hour_to=23) -> dict:
    """Recorte do BI: período, métrica, faixas etárias e janela de horário
    (hour_from > hour_to cruza a meia-noite, ex.: 22 → 2)."""
    today = timezone.localdate()
    since = today - timedelta(days=days - 1)
    hours = Q(hour__gte=hour_from, hour__lte=hour_to) if hour_from <= hour_to else Q(hour__gte=hour_from) | Q(hour__lte=hour_to)
    base = AccessStat.objects.filter(restaurant=restaurant, date__gte=since).filter(hours)
    by_age_qs = base.filter(event__in=METRICS[metric])  # distribuição etária ignora o filtro de idade
    qs = by_age_qs.filter(age__in=ages) if ages else by_age_qs

    def total(q):
        return q.aggregate(n=Sum("count"))["n"] or 0

    # totais dos 3 indicadores no mesmo recorte (idade + horário)
    scoped = base.filter(age__in=ages) if ages else base
    views = total(scoped.filter(event__in=METRICS["views"]))
    impressions = total(scoped.filter(event__in=METRICS["impressions"]))
    clicks = total(scoped.filter(event__in=METRICS["clicks"]))
    if ages:  # recorte por idade: totais também respeitam o K
        views, impressions, clicks = mask(views), mask(impressions), mask(clicks)

    by_hour = dict(qs.values_list("hour").annotate(n=Sum("count")))
    by_day = dict(qs.values_list("date").annotate(n=Sum("count")))
    by_age = dict(by_age_qs.values_list("age").annotate(n=Sum("count")))

    cells = list(
        qs.filter(cell__isnull=False)
        .values("cell__lat", "cell__lon", "cell__label")
        .annotate(n=Sum("count"))
        .order_by("-n")
    )
    regions: dict[str, int] = defaultdict(int)
    for c in cells:
        regions[c["cell__label"] or f"{c['cell__lat']}, {c['cell__lon']}"] += c["n"]
    located = sum(c["n"] for c in cells)
    selected = total(qs)

    return {
        "k": K,
        "window": {"from": since.isoformat(), "to": today.isoformat(), "days": days},
        "filters": {"metric": metric, "ages": ages or [], "hour_from": hour_from, "hour_to": hour_to},
        "totals": {
            "views": views,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": round(clicks / impressions, 4) if clicks and impressions else None,
        },
        "by_hour": [{"hour": h, "count": mask(by_hour.get(h, 0))} for h in range(24)],
        "by_day": [
            {"date": (since + timedelta(days=i)).isoformat(), "count": mask(by_day.get(since + timedelta(days=i), 0))}
            for i in range(days)
        ],
        "by_age": [{"age": value, "label": label, "count": mask(by_age.get(value, 0))} for value, label in AccessStat.Age.choices],
        # só células com K+ acessos vão pro mapa (as pequenas somem, não viram "<K")
        "cells": [
            {"lat": float(c["cell__lat"]), "lon": float(c["cell__lon"]), "label": c["cell__label"], "count": c["n"]}
            for c in cells if c["n"] >= K
        ],
        "regions": [
            {"label": label, "count": n}
            for label, n in sorted(regions.items(), key=lambda kv: -kv[1])[:10] if n >= K
        ],
        "coverage": {"located": mask(located), "total": mask(selected)},
    }
