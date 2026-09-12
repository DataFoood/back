"""Cliente fino do Ollama pra embeddings. Isolado pra ser mockável nos testes."""

import httpx
from django.conf import settings


def embed_text(text: str) -> list[float]:
    """Gera o vetor de embedding de um texto via Ollama.
    Levanta httpx.HTTPError se o Ollama falhar."""
    response = httpx.post(
        f"{settings.OLLAMA_URL}/api/embeddings",
        json={"model": settings.EMBEDDING_MODEL, "prompt": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["embedding"]
