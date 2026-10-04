# Modules

Mapa arquivo-a-arquivo. Apps Django ficam em `dtfd/` (irmãos do pacote de
config).

## Pacote de config — `dtfd/dtfd/`
| Arquivo | Papel |
|---|---|
| `settings.py` | config central: apps, DRF, JWT, CORS, throttle, DB, Celery, Ollama, spectacular |
| `urls.py` | roteamento raiz: `/api/...`, `/api/docs/`, `/api/schema/`, `/admin/` |
| `celery.py` | app Celery (autodiscover de tasks, namespace CELERY) |
| `__init__.py` | importa o `celery_app` |
| `wsgi.py` / `asgi.py` | entrypoints servidor |

## App `users`
Login por **email** (sem username), soft delete, consentimento LGPD.
| Arquivo | Papel |
|---|---|
| `models.py` | `User(AbstractUser, AbstractAudit)`: name, cpf, email, role, `allow_info` |
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
| `views.py` | CRUD aninhado, favoritar, busca (`SearchView` → `embeddings.search`), view-tracking |
| `signals.py` | marca `embedding_stale` quando dado relevante muda |
| `permissions.py` | owner-or-admin (`owner_field`: owner/author), parent-owner-or-admin |
| `apps.py` | `ready()` conecta os signals |

## App `address`
Endereço polimórfico via **GenericForeignKey** (restaurant ou user).
| Arquivo | Papel |
|---|---|
| `models.py` | `Address` com content_type/object_id |
| `serializers.py` | `entity_type` (string) → ContentType; valida alvo existe |
| `views.py` / `permissions.py` / `urls.py` | CRUD + dono-da-entidade-ou-admin; dispara geocoding do endereço de restaurante |
| `geocoding.py` / `tasks.py` | Nominatim: endereço → lat/lon, coordenada → nome da região (1 req/s) |
| `management/commands/geocode_addresses.py` | backfill das coordenadas |

## App `preferences`
Afinidades do usuário derivadas dos sinais.
| Arquivo | Papel |
|---|---|
| `models.py` | RankingWeight, SearchHistory, afinidades (cuisine/ambient/price) |
| `services.py` | `compute_user_preferences` (view×1 + favorite×5, normaliza por dimensão) |
| `tasks.py` | `recompute_all` (Celery beat) |
| `views.py` | ver preferências, editar afinidade (→ is_manual), histórico |

## App `embeddings`
Geração e armazenamento dos vetores + busca semântica.
| Arquivo | Papel |
|---|---|
| `models.py` | `RestaurantEmbedding` (OneToOne, VectorField 768) |
| `documents.py` | monta o texto-documento do restaurante p/ embeddar |
| `ollama.py` | cliente do Ollama (nomic-embed-text) |
| `services.py` | `reindex_restaurant` / `reindex_all` (isolado por item) |
| `search.py` | busca: embed → kNN (pgvector) → `rank()` z-score ponderado |
| `tasks.py` | `reindex_stale` (Celery beat) |
| `migrations/0001` | inclui `VectorExtension()` (cria extensão pgvector) |

## App `analytics`
Métricas agregadas e anônimas. Detalhe em [[search-rag]].
| Arquivo | Papel |
|---|---|
| `models.py` | `RestaurantDailyStat`, `GeoCell`, `RegionVisit`, `PlatformDailyStat` |
| `services.py` | `bump_restaurants` / `bump_platform` (2 queries, sem corrida), `record_region_visit` |
| `tasks.py` | `label_cell` (reverse geocoding da célula) |
| `views.py` | `PlatformMetricsView` (admin) |

## App `utils`
Infra compartilhada.
| Arquivo | Papel |
|---|---|
| `AbstractAudit.py` | `AbstractAudit` (created/updated/deleted_at, `soft_delete()`) + `ActiveManager` |
| `pagination.py` | `DefaultPagination` (10/pág, máx 50) |

Relações entre os modelos em [[data-model]].
