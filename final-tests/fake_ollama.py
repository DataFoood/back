"""Ollama falso para testes locais sem GPU/modelo.

Implementa só `POST /api/embeddings` (o único endpoint que Django e shinzou
usam) devolvendo um vetor determinístico de EMBEDDING_DIM dimensões:
bag-of-words com hashing + normalização L2. Não é semântico de verdade, mas
textos que compartilham palavras ficam próximos — o suficiente para exercitar
o pipeline inteiro (reindex -> pgvector -> kNN -> ranking -> hidratação).

Uso:
    uv run python final-tests/fake_ollama.py            # porta 11434
    FAKE_OLLAMA_PORT=11500 uv run python final-tests/fake_ollama.py
"""

import hashlib
import json
import math
import os
import re
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
PORT = int(os.environ.get("FAKE_OLLAMA_PORT", "11434"))
STOPWORDS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "um", "uma",
             "para", "pra", "com", "em", "no", "na", "que", "por", "lugar"}


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9]+", text) if len(t) > 2 and t not in STOPWORDS]


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in _tokens(text):
        # prefixo de 5 letras aproxima flexões (jantar/jantares, tranquilo/tranquila)
        for piece in {tok, tok[:5]}:
            h = int(hashlib.sha256(piece.encode()).hexdigest(), 16)
            vec[h % DIM] += 1.0 if (h >> 12) % 2 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    # vetor nulo quebraria o cosseno do pgvector: usa um eixo fixo
    return [v / norm for v in vec] if any(vec) else [1.0] + [0.0] * (DIM - 1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # healthcheck / `ollama list`
        self._send(200, {"models": [{"name": os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")}]})

    def do_POST(self):
        if self.path.rstrip("/") != "/api/embeddings":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._send(200, {"embedding": embed(str(body.get("prompt", "")))})

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silencioso
        pass


if __name__ == "__main__":
    print(f"fake ollama em http://localhost:{PORT} (dim={DIM})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
