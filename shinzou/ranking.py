"""Ranking por z-score ponderado. Função pura, sem DB — fácil de testar.

Cada sinal (similaridade semântica, preferência, review) é normalizado
para z-score (média 0, desvio 1) no conjunto de candidatos. Combina com
pesos e ordena. Texto/semântica tem o maior peso -> não é sobreposto
pela preferência (requisito do usuário)."""

from dataclasses import dataclass
from statistics import pstdev, mean


@dataclass
class Candidate:
    restaurant_id: int
    semantic: float   # similaridade 0..1
    preference: float # afinidade agregada
    review: float     # rating médio


def _zscores(values: list[float]) -> list[float]:
    if not values:
        return []
    mu = mean(values)
    sigma = pstdev(values)
    if sigma == 0:
        return [0.0 for _ in values]
    return [(v - mu) / sigma for v in values]


def rank(
    candidates: list[Candidate],
    w_semantic: float,
    w_preference: float,
    w_review: float,
    limit: int,
) -> list[tuple[int, float]]:
    """Retorna [(restaurant_id, score)] ordenado desc, cortado em `limit`."""
    if not candidates:
        return []

    z_sem = _zscores([c.semantic for c in candidates])
    z_pref = _zscores([c.preference for c in candidates])
    z_rev = _zscores([c.review for c in candidates])

    scored = []
    for c, zs, zp, zr in zip(candidates, z_sem, z_pref, z_rev):
        score = w_semantic * zs + w_preference * zp + w_review * zr
        scored.append((c.restaurant_id, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]
