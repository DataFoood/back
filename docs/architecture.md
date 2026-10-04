# Architecture

DataFood = backend de descoberta de restaurantes com busca semântica (RAG).
Um serviço de aplicação (Django) + infra de apoio.

## Serviços
```
                    ┌────────────────────────────────────────────┐
  frontend  ──────▶ │  Django / DRF  (web :8000)   [único exposto] │
  (browser)         │  - REST API, auth JWT, CRUD, regras          │
                    │  - busca semântica (embeddings/search.py)    │
                    └───┬─────────────┬──────────────┬─────────────┘
                        │             │              │
            ┌───────────▼──┐   ┌──────▼──────┐   ┌───▼────────┐
            │ Postgres     │   │ Redis       │   │ Ollama     │
            │ + pgvector   │   │ broker/cache│   │ embeddings │
            └───────▲──────┘   └─────────────┘   └───▲────────┘
                    │                                │
            ┌───────┴───────┐                        │
            │ Celery worker │────────────────────────┘
            │ + beat (cron) │   (reindex)
            └───────────────┘
```

| Serviço | Papel | Exposto? |
|---|---|---|
| **web** (Django) | API REST, auth, CRUD, busca semântica | **Sim** (:8000) |
| **worker/beat** (Celery) | indexação e recompute assíncronos + cron | Não |
| **db** (Postgres+pgvector) | dados + vetores | Não |
| **redis** | broker Celery + cache de throttle | Não |
| **ollama** | gera embeddings (nomic-embed-text) | Não |

Detalhes de portas/env em [[infrastructure]].

## Fluxo de um request normal (CRUD)
1. Front manda `Authorization: Bearer <access>` pro Django.
2. DRF autentica (JWT), checa permissão, valida no serializer.
3. View executa, ORM fala com Postgres, retorna JSON.

## Fluxo de uma busca semântica
Front → `POST /api/search/` no Django → embeda a query (Ollama), kNN no
pgvector via ORM, rerankeia com preferências do usuário → cards rankeados.
Detalhe completo em [[search-rag]].

## Por que um serviço só
Até 2026-10 a busca rodava num serviço FastAPI separado (shinzou), mas ele lia
as tabelas do Django por SQL cru e revalidava o mesmo JWT: acoplamento total
sem isolamento real. A busca virou um módulo do Django (`embeddings/search.py`).
O trabalho pesado é do Ollama, que continua sendo um container à parte.

## Decisões estruturais
- **Apps no topo do sys.path:** imports são `from users.models import User`
  (apps são irmãos do pacote de config `dtfd/`), não `dtfd.users`.
- **Indexação assíncrona:** mudou dado relevante → signal marca
  `embedding_stale=True`; o Celery reprocessa em background. CRUD não espera IA.
- **Soft delete em tudo** via `AbstractAudit`. Ver [[data-model]].

Mapa de arquivos em [[modules]]. Segurança em [[security]].
