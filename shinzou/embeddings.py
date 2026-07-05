"""Embedda a query do usuário via Ollama (mesmo modelo do Django)."""

import httpx

from .config import settings


def embed_query(text: str) -> list[float]:
    response = httpx.post(
        f"{settings.OLLAMA_URL}/api/embeddings",
        json={"model": settings.EMBEDDING_MODEL, "prompt": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["embedding"]
