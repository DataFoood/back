import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name, default=""):
    """Lista separada por ';' (ou ',') vinda do env, sem itens vazios."""
    raw = os.environ.get(name, default).replace(",", ";")
    return [item.strip() for item in raw.split(";") if item.strip()]


# Seguro por padrão: sem DEBUG explícito, roda em modo produção.
DEBUG = os.environ.get("DEBUG", "False") == "True"

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("SECRET_KEY é obrigatório com DEBUG=False.")
    SECRET_KEY = "django-insecure-local-only"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost;127.0.0.1" if DEBUG else "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "users",
    "address",
    "restaurants",
    "preferences",
    "embeddings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dtfd.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "dtfd.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "dtfd"),
        "USER": os.environ.get("DB_USER", "dtfd"),
        "PASSWORD": os.environ.get("DB_PASS", "dtfd"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "users.User"

# Cache compartilhado (Redis) — usado pelo throttle do DRF. Em prod com
# multiplos workers, contador precisa ser compartilhado, nao por processo.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://redis:6379/1"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# CORS — em dev, localhost nas portas comuns de frontend. Em produção, as
# origens reais vêm de CORS_ALLOWED_ORIGINS (ex: https://app.datafood.com.br).
_DEV_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (3000, 3001, 3002, 5000, 5001, 5002)
]
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS") or (_DEV_ORIGINS if DEBUG else [])
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Quantos proxies confiáveis ficam na frente da API. O throttle identifica
    # o cliente pelo IP: sem isso o DRF usa o X-Forwarded-For inteiro (que o
    # cliente forja) e o limite de login vira bypassável. 0 = sem proxy (usa
    # REMOTE_ADDR); 1 = atrás do Caddy (docker-compose.prod.yml).
    "NUM_PROXIES": int(os.environ.get("NUM_PROXIES", "0")),
    # rates por escopo, aplicados via ScopedRateThrottle nas views sensiveis
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/min",
        "register": "10/hour",
        # busca é cara (embedding + kNN): limita por usuário
        "search": os.environ.get("SEARCH_RATE", "30/min"),
    },
    # OpenAPI/Swagger (handoff frontend)
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "15"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("JWT_REFRESH_DAYS", "7"))
    ),
    # refresh rotaciona a cada uso e o antigo vai pra blacklist
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "DataFood API",
    "DESCRIPTION": "Backend de descoberta de restaurantes com busca semântica (RAG).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # JWT Bearer no Swagger "Authorize"
    "SECURITY": [{"jwtAuth": []}],
}

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # httpx loga toda request em INFO (embeddings/shinzou) — ruído
    "loggers": {"httpx": {"level": "WARNING"}},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Embeddings / Ollama ---------------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))

# --- Ponte B2B com o shinzou (busca semântica) -----------------------------
SHINZOU_URL = os.environ.get("SHINZOU_URL", "http://shinzou:8001")
SHINZOU_SERVICE_TOKEN = os.environ.get("SHINZOU_SERVICE_TOKEN", "dev-service-token")
if not DEBUG and SHINZOU_SERVICE_TOKEN in ("", "dev-service-token"):
    raise ImproperlyConfigured("Defina SHINZOU_SERVICE_TOKEN em produção.")

# --- Celery (indexação assíncrona; reusa o Redis) --------------------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False") == "True"

from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "reindex-stale-hourly": {
        "task": "embeddings.tasks.reindex_stale",
        "schedule": crontab(minute=0),  # toda hora cheia
    },
    "recompute-preferences-daily": {
        "task": "preferences.tasks.recompute_all",
        "schedule": crontab(minute=30, hour=3),  # 03:30
    },
}

# --- Seguranca de producao -------------------------------------------------
# Em dev (DEBUG=True) fica tudo desligado. Em prod (DEBUG=False via env)
# ativa cookies seguros, redirect HTTPS e HSTS. Atras de proxy/nginx,
# SECURE_PROXY_SSL_HEADER faz o Django confiar no X-Forwarded-Proto.
if not DEBUG:
    # SECURE_SSL_REDIRECT=False quando o TLS termina num proxy que já redireciona
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True") == "True"
    # healthcheck interno (http) não pode tomar redirect
    SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
