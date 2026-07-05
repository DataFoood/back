"""Config do shinzou, tudo via env (mesma .env do Django)."""

import os


class Settings:
    # Auth — mesma SECRET_KEY do Django (valida o JWT do simplejwt, HS256)
    SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-local-only")
    JWT_ALGORITHM = "HS256"
    # Token de servico Django -> shinzou (camada B2B)
    SERVICE_TOKEN = os.environ.get("SHINZOU_SERVICE_TOKEN", "dev-service-token")

    # Banco (mesmo Postgres do Django)
    DB_NAME = os.environ.get("DB_NAME", "dtfd")
    DB_USER = os.environ.get("DB_USER", "dtfd")
    DB_PASS = os.environ.get("DB_PASS", "dtfd")
    DB_HOST = os.environ.get("DB_HOST", "db")
    DB_PORT = os.environ.get("DB_PORT", "5432")
    DB_POOL_MAX = int(os.environ.get("SHINZOU_DB_POOL_MAX", "10"))

    # Ollama (mesmo modelo do Django -> vetores compativeis)
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

    # Pipeline
    CANDIDATE_POOL = int(os.environ.get("SHINZOU_CANDIDATE_POOL", "50"))
    RESULT_LIMIT = int(os.environ.get("SHINZOU_RESULT_LIMIT", "15"))
    MAX_LIMIT = int(os.environ.get("SHINZOU_MAX_LIMIT", "50"))

    # Pesos do ranking (z-score ponderado). Texto manda mais que preferencia.
    # FLAG: vira tabela gerenciavel (fast-follow).
    WEIGHT_SEMANTIC = float(os.environ.get("SHINZOU_W_SEMANTIC", "1.0"))
    WEIGHT_PREFERENCE = float(os.environ.get("SHINZOU_W_PREFERENCE", "0.5"))
    WEIGHT_REVIEW = float(os.environ.get("SHINZOU_W_REVIEW", "0.3"))


settings = Settings()
