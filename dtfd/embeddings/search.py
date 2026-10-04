"""Busca semântica de restaurantes por linguagem natural.

Pipeline:
  query NL -> embed (Ollama) -> kNN (pgvector) -> sinais (similaridade,
  preferência, review, proximidade) -> z-score ponderado -> top N.
"""

import math
from dataclasses import dataclass
from statistics import mean, pstdev

from django.contrib.contenttypes.models import ContentType
from pgvector.django import CosineDistance

from address.models import Address
from preferences.models import RankingWeight
from preferences.services import DIMENSIONS
from restaurants.models import Restaurant

from .models import RestaurantEmbedding
from .ollama import embed_text

# quantos vizinhos do kNN entram no ranking
CANDIDATE_POOL = 50
# fallback se a chave sumir da tabela RankingWeight (editável no admin).
# Texto manda mais que preferência e que distância.
DEFAULT_WEIGHTS = {"semantic": 1.0, "preference": 0.5, "review": 0.3, "distance": 0.5}
EARTH_RADIUS_KM = 6371.0


@dataclass
class Candidate:
    restaurant_id: int
    semantic: float                # similaridade 0..1
    preference: float              # afinidade agregada
    review: float                  # rating médio
    distance_km: float | None = None  # None = sem localização (usuário ou restaurante)


def _zscores(values: list[float | None]) -> list[float]:
    """z-score dos valores conhecidos; None vira 0 (= média, sinal neutro)."""
    known = [v for v in values if v is not None]
    if not known:
        return [0.0 for _ in values]
    mu = mean(known)
    sigma = pstdev(known)
    if sigma == 0:
        return [0.0 for _ in values]
    return [0.0 if v is None else (v - mu) / sigma for v in values]


def rank(candidates: list[Candidate], weights: dict[str, float], limit: int) -> list[tuple[int, float]]:
    """Ranking por z-score ponderado. Função pura, sem DB.

    Cada sinal é normalizado para z-score (média 0, desvio 1) no conjunto de
    candidatos, combinado com os pesos e ordenado. Distância entra negativa
    (mais perto = melhor). Retorna [(restaurant_id, score)] desc, cortado em `limit`."""
    if not candidates:
        return []

    signals = {
        "semantic": _zscores([c.semantic for c in candidates]),
        "preference": _zscores([c.preference for c in candidates]),
        "review": _zscores([c.review for c in candidates]),
        "distance": _zscores([None if c.distance_km is None else -c.distance_km for c in candidates]),
    }
    scored = [
        (c.restaurant_id, sum(weights[key] * z[i] for key, z in signals.items()))
        for i, c in enumerate(candidates)
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _distances(origin: tuple[float, float], restaurant_ids: list[int]) -> dict[int, float]:
    """km da origem até o endereço (default primeiro) de cada restaurante geocodificado."""
    rows = (
        Address.objects.filter(
            content_type=ContentType.objects.get_for_model(Restaurant),
            object_id__in=restaurant_ids,
            latitude__isnull=False,
            longitude__isnull=False,
        )
        .order_by("is_default")  # False antes de True: o default sobrescreve no dict
        .values_list("object_id", "latitude", "longitude")
    )
    return {rid: haversine_km(*origin, float(lat), float(lon)) for rid, lat, lon in rows}


def _preference_scores(user, restaurant_ids: list[int]) -> dict[int, float]:
    """Soma das afinidades do usuário com as taxonomias de cada restaurante."""
    scores = dict.fromkeys(restaurant_ids, 0.0)
    for m2m_field, AffinityModel, fk_name in DIMENSIONS:
        affinities = dict(
            AffinityModel.objects.filter(user=user).values_list(f"{fk_name}_id", "score")
        )
        if not affinities:
            continue
        pairs = Restaurant.objects.filter(id__in=restaurant_ids).values_list("id", m2m_field)
        for rid, value_id in pairs:
            scores[rid] += affinities.get(value_id, 0.0)
    return scores


def search(
    user,
    query: str,
    limit: int,
    origin: tuple[float, float] | None = None,
    radius_km: float | None = None,
) -> list[tuple[int, float, float, float | None]]:
    """[(restaurant_id, score, similarity, distance_km)] em ordem de ranking.

    `origin` = (lat, lon) do usuário, só usada neste request (não é guardada).
    Com `radius_km`, restaurantes fora do raio ou sem coordenada saem.
    Levanta httpx.HTTPError se o Ollama falhar."""
    vector = embed_text(query)
    knn = list(
        RestaurantEmbedding.objects.filter(restaurant__deleted_at__isnull=True)
        .annotate(distance=CosineDistance("embedding", vector))
        .order_by("distance")
        .values_list("restaurant_id", "distance", "restaurant__average_rating")[:CANDIDATE_POOL]
    )
    if not knn:
        return []

    similarity = {rid: 1 - distance for rid, distance, _ in knn}
    distances = _distances(origin, list(similarity)) if origin else {}
    if origin and radius_km is not None:
        knn = [row for row in knn if distances.get(row[0], math.inf) <= radius_km]
    preference = _preference_scores(user, list(similarity))
    candidates = [
        Candidate(rid, similarity[rid], preference[rid], float(rating), distances.get(rid))
        for rid, _, rating in knn
    ]

    weights = {**DEFAULT_WEIGHTS, **dict(RankingWeight.objects.values_list("key", "weight"))}
    return [
        (rid, score, similarity[rid], distances.get(rid))
        for rid, score in rank(candidates, weights, limit)
    ]
