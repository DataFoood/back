"""shinzou — busca de restaurantes por linguagem natural.

Pipeline:
  query NL -> embed -> kNN (pgvector) -> sinais (similaridade, preferência,
  review) -> z-score ponderado -> top N.
"""

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from . import db, embeddings
from .auth import get_user_id, verify_service_token
from .config import settings
from .ranking import Candidate, rank

app = FastAPI(title="shinzou", description="Busca semântica de restaurantes")


class SearchRequest(BaseModel):
    query: str
    limit: int | None = None


def _preference_score(rid: int, signals: dict, affinities: dict) -> float:
    """Soma das afinidades do usuário com as taxonomias do restaurante."""
    total = 0.0
    for dim in ("cuisines", "ambients", "prices"):
        values = signals[dim].get(rid, set())
        affs = affinities.get(dim, {})
        total += sum(affs.get(v, 0.0) for v in values)
    return total


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search", dependencies=[Depends(verify_service_token)])
def search(req: SearchRequest, user_id: int = Depends(get_user_id), conn=Depends(db.get_db)):
    try:
        vector = embeddings.embed_query(req.query)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Serviço de embedding indisponível.")

    knn = db.knn_candidates(conn, vector, settings.CANDIDATE_POOL)
    if not knn:
        return {"results": []}

    ids = [rid for rid, _ in knn]
    similarity = {rid: sim for rid, sim in knn}
    signals = db.restaurant_signals(conn, ids)
    affinities = db.user_affinities(conn, user_id)

    candidates = [
        Candidate(
            restaurant_id=rid,
            semantic=similarity[rid],
            preference=_preference_score(rid, signals, affinities),
            review=signals["ratings"].get(rid, 0.0),
        )
        for rid in ids
    ]

    weights = db.ranking_weights(conn)
    # clamp do limit: 1..MAX_LIMIT (evita pedido abusivo)
    limit = min(req.limit or settings.RESULT_LIMIT, settings.MAX_LIMIT)
    limit = max(limit, 1)
    ranked = rank(
        candidates,
        weights.get("semantic", settings.WEIGHT_SEMANTIC),
        weights.get("preference", settings.WEIGHT_PREFERENCE),
        weights.get("review", settings.WEIGHT_REVIEW),
        limit,
    )

    hydrated = db.hydrate(conn, [rid for rid, _ in ranked])
    results = [
        {"restaurant": hydrated.get(rid), "score": round(score, 4)}
        for rid, score in ranked
    ]
    return {"results": results}
