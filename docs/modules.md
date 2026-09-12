# Modules

Mapa arquivo-a-arquivo. Apps Django ficam em `dtfd/` (irmãos do pacote de
config). Serviço de busca em `shinzou/`.

## Pacote de config — `dtfd/dtfd/`
| Arquivo | Papel |
|---|---|
| `settings.py` | config central: apps, DRF, JWT, CORS, throttle, DB, Celery, Ollama, shinzou, spectacular |
| `urls.py` | roteamento raiz: `/api/...`, `/api/docs/`, `/api/schema/`, `/admin/` |
| `celery.py` | app Celery (autodiscover de tasks, namespace CELERY) |
| `__init__.py` | importa o `celery_app` |
| `wsgi.py` / `asgi.py` | entrypoints servidor |

## App `users`
Login por **email** (sem username), soft delete, consentimento LGPD.
| Arquivo | Papel |
|---|---|
| `models.py` | `User(AbstractUser, AbstractAudit)`: name, cpf, email, role, level, `allow_info` |
| `managers.py` | `UserManager` — create_user/superuser por email; filtra soft-deleted |
| `serializers.py` | Create (confirm_password), Detail, Update, ChangePassword |
| `views.py` | register, login (JWT throttled), detail/update, delete (soft), consent, change-password, list/removed (admin) |
| `permissions.py` | `IsOwnerOrAdmin` |
| `urls.py` | rotas `/api/users/...` |

## App `restaurants`
Núcleo do domínio + sinais de preferência.
| Arquivo | Papel |
|---|---|
| `models.py` | Restaurant + 7 taxonomias (BaseLookup) + Image/Review/BusinessHour/Item/Favorite/View |
| `serializers.py` | CRUD + validações (ex.: máx 6 itens) |
| `views.py` | CRUD aninhado, favoritar, busca (ponte shinzou), view-tracking |
| `signals.py` | marca `embedding_stale` quando dado relevante muda |
| `permissions.py` | owner/author/parent-owner-or-admin |
| `apps.py` | `ready()` conecta os signals |

## App `address`
Endereço polimórfico via **GenericForeignKey** (restaurant ou user).
| Arquivo | Papel |
|---|---|
| `models.py` | `Address` com content_type/object_id |
| `serializers.py` | `entity_type` (string) → ContentType; valida alvo existe |
| `views.py` / `permissions.py` / `urls.py` | CRUD + dono-da-entidade-ou-admin |

## App `preferences`
Afinidades do usuário derivadas dos sinais.
| Arquivo | Papel |
|---|---|
| `models.py` | RankingWeight, SearchHistory, afinidades (cuisine/ambient/price) |
| `services.py` | `compute_user_preferences` (view×1 + favorite×5, normaliza por dimensão) |
| `tasks.py` | `recompute_all` / `recompute_one` (Celery) |
| `views.py` | ver preferências, editar afinidade (→ is_manual), histórico, recompute (admin) |

## App `embeddings`
Geração e armazenamento dos vetores.
| Arquivo | Papel |
|---|---|
| `models.py` | `RestaurantEmbedding` (OneToOne, VectorField 768) |
| `documents.py` | monta o texto-documento do restaurante p/ embeddar |
| `ollama.py` | cliente do Ollama (nomic-embed-text) |
| `services.py` | `reindex_restaurant` / `reindex_all` (isolado por item) |
| `tasks.py` | `reindex_stale` / `reindex_all_task` / `reindex_one` (Celery) |
| `views.py` | `ReindexView` (admin, async, 202) |
| `migrations/0001` | inclui `VectorExtension()` (cria extensão pgvector) |

## App `utils`
Infra compartilhada.
| Arquivo | Papel |
|---|---|
| `AbstractAudit.py` | `AbstractAudit` (created/updated/deleted_at) + `ActiveManager` |
| `pagination.py` | `DefaultPagination` (10/pág, máx 50) |

## Serviço `shinzou/` (FastAPI)
Busca semântica. Lê o **mesmo** Postgres por SQL cru. Detalhe em
[[search-rag]].
| Arquivo | Papel |
|---|---|
| `main.py` | endpoint `/search`; embeda, busca candidatos, rerankeia |
| `config.py` | settings (SECRET_KEY compartilhada, pesos, limites, DB pool) |
| `db.py` | `ThreadedConnectionPool` + `get_db()` (DI); queries kNN/sinais/pesos |
| `auth.py` | service token (constant-time) + valida JWT (claim token_type=access) |
| `embeddings.py` | embeda a query via Ollama |
| `ranking.py` | z-score + soma ponderada (semântico/preferência/review) |

Relações entre os modelos em [[data-model]].
