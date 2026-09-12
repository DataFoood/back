# Infrastructure

Tudo sobe via Docker Compose. Gerência de deps com `uv` (`pyproject.toml` +
`uv.lock`).

## Subir
```bash
docker compose up -d --build
```
Django em `http://localhost:8000`. A 1ª subida puxa o modelo de embedding no
Ollama (`ollama-init`) antes do web ficar pronto — pode demorar.

> `docker compose restart` **não** relê o `.env`. Pra aplicar mudança de env:
> `docker compose up -d --force-recreate` (ou `--build` se mudou dependência).

## Serviços (docker-compose.yml)
| Serviço | Imagem/cmd | Porta host:container | Papel |
|---|---|---|---|
| `db` | pgvector/pgvector:pg16 | **5433**:5432 | Postgres + pgvector |
| `redis` | redis | — | broker Celery + cache throttle |
| `ollama` | ollama | **11435**:11434 | embeddings |
| `ollama-init` | ollama (one-shot) | — | puxa `EMBEDDING_MODEL` e sai |
| `web` | Django runserver | **8000**:8000 | API (único exposto ao front) |
| `worker` | celery -A dtfd worker | — | tasks assíncronas |
| `beat` | celery -A dtfd beat | — | cron (reindex/recompute) |
| `shinzou` | uvicorn shinzou.main:app | **8001**:8001 | busca (interno) |

Portas host 5433/11435 evitam conflito com Postgres/Ollama já rodando na
máquina. Detalhe dos papéis em [[architecture]].

## Redis — bancos lógicos
| DB | Uso |
|---|---|
| /0 | broker Celery |
| /1 | cache (throttle DRF) |
| /2 | result backend Celery |

## Variáveis de ambiente (.env)
| Var | Exemplo | Nota |
|---|---|---|
| `DB_NAME/DB_USER/DB_PASS/DB_HOST/DB_PORT` | dtfd / dtfd / ... / db / 5432 | Postgres |
| `REDIS_URL` | redis://redis:6379/1 | cache |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | redis://redis:6379/0 e /2 | |
| `OLLAMA_URL` | http://ollama:11434 | |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | nomic-embed-text / 768 | |
| `SHINZOU_URL` | http://shinzou:8001 | ponte |
| `SHINZOU_SERVICE_TOKEN` | (segredo) | auth de serviço |
| `SECRET_KEY` | (segredo) | compartilhada Django↔shinzou (JWT) |
| `ALLOWED_HOSTS` | separado por `;` | parsing custom no settings |

`.env.example` lista o conjunto. Segredos reais ficam fora do git.

## Cron (Celery beat)
| Task | Agenda |
|---|---|
| `embeddings.tasks.reindex_stale` | de hora em hora (minuto 0) |
| `preferences.tasks.recompute_all` | diário 03:30 |

## Qualidade
- Testes: `docker compose exec -w /app/dtfd web uv run python manage.py test`
  (138 Django) + `shinzou/tests` (6).
- Tipos: `pyright` (config em `pyrightconfig.json`) — 0 erros.
- Schema: `manage.py spectacular --validate` — 0 erros.
