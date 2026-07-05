# Architecture

DataFood = backend de descoberta de restaurantes com busca semântica (RAG).
Dois serviços de aplicação + infra de apoio.

## Serviços
```
                    ┌────────────────────────────────────────────┐
  frontend  ──────▶ │  Django / DRF  (web :8000)   [único exposto] │
  (browser)         │  - REST API, auth JWT, CRUD, regras          │
                    │  - ponte de busca p/ o shinzou               │
                    └───┬─────────────┬──────────────┬─────────────┘
                        │             │              │
            ┌───────────▼──┐   ┌──────▼──────┐   ┌───▼───────────────┐
            │ Postgres     │   │ Redis       │   │ shinzou (:8001)   │
            │ + pgvector   │   │ broker/cache│   │ FastAPI [interno] │
            └───────▲──────┘   └─────────────┘   │ busca semântica   │
                    │                            └───┬───────────────┘
            ┌───────┴───────┐    ┌───────────┐       │ lê o MESMO Postgres
            │ Celery worker │    │ Ollama     │◀──────┘ (SQL cru)
            │ + beat (cron) │    │ embeddings │
            └───────────────┘    └───────────┘
```

| Serviço | Papel | Exposto? |
|---|---|---|
| **web** (Django) | API REST, auth, CRUD, orquestração | **Sim** (:8000) |
| **shinzou** (FastAPI) | busca semântica/ranking | Não (interno :8001) |
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
Front → `POST /api/search/` no Django → Django repassa ao **shinzou** (service
token + JWT) → shinzou embeda a query (Ollama), faz kNN no pgvector, rerankeia
com preferências do usuário, devolve ranking → Django retorna ao front.
Detalhe completo em [[search-rag]].

## Por que dois serviços
O Django concentra regra de negócio e é a única superfície pública. A busca
(IA/vetorial, mais pesada e com dependências próprias) fica isolada no shinzou,
interno, escalável à parte. O front nunca fala direto com o shinzou.

## Decisões estruturais
- **Apps no topo do sys.path:** imports são `from users.models import User`
  (apps são irmãos do pacote de config `dtfd/`), não `dtfd.users`.
- **Indexação assíncrona:** mudou dado relevante → signal marca
  `embedding_stale=True`; o Celery reprocessa em background. CRUD não espera IA.
- **Soft delete em tudo** via `AbstractAudit`. Ver [[data-model]].

Mapa de arquivos em [[modules]]. Segurança em [[security]].
