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
| `NUM_PROXIES` | 0 (dev) / 1 (prod, Caddy) | quantos proxies confiáveis ficam na frente — define o IP usado no rate limit ([[security]]) |
| `SEARCH_RATE` | 30/min | throttle da busca por usuário |

`.env.example` lista o conjunto. Segredos reais ficam fora do git.

## Rodar sem Docker (testes locais)
Útil em máquina/CI sem Docker. Precisa de Postgres 16 com a extensão
`vector` (pacote `postgresql-16-pgvector`) e Redis.

```bash
# banco
sudo -u postgres psql -c "CREATE USER dtfd WITH PASSWORD 'dtfd' SUPERUSER;"
sudo -u postgres createdb -O dtfd dtfd
# env apontando para localhost
export DEBUG=True DB_HOST=localhost REDIS_URL=redis://localhost:6379/1 \
  CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/2 \
  OLLAMA_URL=http://localhost:11434 SHINZOU_URL=http://localhost:8001 CELERY_TASK_ALWAYS_EAGER=True
uv sync
uv run python final-tests/fake_ollama.py &          # embeddings determinísticos, sem GPU
uv run uvicorn shinzou.main:app --port 8001 &
cd dtfd && uv run python manage.py migrate && uv run python manage.py seed_demo --demo-users \
  && uv run python manage.py reindex_restaurants && uv run python manage.py runserver
```

O `fake_ollama.py` responde `POST /api/embeddings` com bag-of-words hasheado
(768 dims): não é semântico, mas exercita o pipeline inteiro (reindex →
pgvector → kNN → ranking). Detalhes em `final-tests/README.md`.

## Cron (Celery beat)
| Task | Agenda |
|---|---|
| `embeddings.tasks.reindex_stale` | de hora em hora (minuto 0) |
| `preferences.tasks.recompute_all` | diário 03:30 |

## Qualidade
- Testes: `docker compose exec -w /app/dtfd web uv run python manage.py test`
  (178 Django) + `shinzou/tests` (6).
- Regressões de segurança: `cd dtfd && uv run python manage.py test ../final-tests` (16).
- Smoke contra o stack rodando: `uv run python final-tests/api_smoke.py` (67 checagens).
- Tipos: `pyright --pythonpath .venv/bin/python` — 20 erros **pré-existentes**
  de stubs (`request.user` tipado como `_User`/`AnonymousUser`, mixins sem
  base tipada); nenhum novo. Zerar é item do [[backlog]].
- Schema: `manage.py spectacular --validate --fail-on-warn` — 0 erros.
