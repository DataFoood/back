FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY dtfd/ ./dtfd/
COPY shinzou/ ./shinzou/

# roda sem root; staticfiles precisa ser gravável pelo collectstatic
RUN useradd --system --uid 1000 --home /app app \
    && mkdir -p /app/dtfd/staticfiles \
    && chown -R app:app /app
USER app

WORKDIR /app/dtfd
