"""Embedda a query do usuário via Ollama (mesmo modelo do Django)."""

import httpx

from .config import settings


def embed_query(text: str) -> list[float]:
    response = httpx.post(
        f"{settings.OLLAMA_URL}/api/embed",
        json={
            "model": settings.EMBEDDING_MODEL, "input": text, "truncate": True,
            "keep_alive": settings.EMBEDDING_KEEP_ALIVE,
            "options": {
                "num_ctx": settings.EMBEDDING_NUM_CTX,
                "num_batch": settings.EMBEDDING_NUM_BATCH,
                "num_thread": settings.EMBEDDING_NUM_THREAD,
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["embeddings"][0]
