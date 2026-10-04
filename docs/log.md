# Log

Registro cronológico (append-only). Mais recente no topo.

## 2026-10-04 — promoção relâmpago
- App `promotions`: o dono põe itens do cardápio com desconto (% ou R$) até uma
  hora de expiração (máx 24 h). Card ganha `promotion` (resumo), detalhe a
  promoção completa com preço final; catálogo filtra `?promo=true`.
- Cardápio sobe de 6 para 30 itens.
- 233 testes Django + 15 regressões.

## 2026-10-04 — métricas v2 (BI do dono)
- `AccessStat` substitui `RestaurantDailyStat`/`RegionVisit`: acessos por dia ×
  hora × evento × faixa etária (com consentimento) × célula de ~1 km.
- `GET /api/analytics/restaurants/<id>/` com filtros (período, métrica, idade,
  horário) e k-anonimato K=5. `seed_analytics_demo` pra demonstração.
- 227 testes Django + 15 regressões.

## 2026-10-04 — proximidade, métricas do dono e console admin
- **Geocoding** de endereço de restaurante via Nominatim (task Celery depois do
  commit; `manage.py geocode_addresses` pra backfill).
- **Busca por proximidade:** `lat`/`lon`/`radius_km` no `POST /api/search/` e
  no catálogo (`ordering=distance`); 4º sinal `distance` no ranking (peso na
  tabela `RankingWeight`, seed 0.5). Coordenada do usuário não é guardada.
- **App `analytics`:** visitas/dia, aparições na busca, cliques vindos da busca e
  visitas por região (~1 km) por restaurante; buscas/falhas da plataforma.
  `stats/` do dono ampliado.
- **Admin:** `GET/PATCH /api/preferences/weights/`, `PATCH /api/users/<id>/admin/`
  (papel/ativação), `?q=`/`?role=` em `/api/users/`,
  `/api/restaurants/admin/`, `restore/`, `reindex/`, `GET /api/analytics/platform/`.
- `createsuperuser` agora cria `role=admin` (migration corrige os existentes).
- Front novo (`dtfd_fte`) integrado a tudo isso.
- 220 testes Django + 15 regressões + smoke 67/67 + fluxo do `dtfd_fte` 32/32.

## 2026-10-04 — cortes de over-engineering (ponytail audit)
- **shinzou (FastAPI) absorvido pelo Django:** a busca virou
  `embeddings/search.py` (kNN via ORM `CosineDistance`, mesmo `rank()` z-score).
  Saíram o service token, a revalidação de JWT, o SQL cru com nome de tabela,
  o pool próprio, a hidratação duplicada e os knobs de env sem uso
  (`SHINZOU_*`). Contrato de `POST /api/search/` inalterado.
- Removidas as rotas admin `POST /api/preferences/recompute/` e
  `POST /api/embeddings/reindex/` (o front não usa); ficam o beat e os
  `manage.py reindex_restaurants` / `recompute_preferences`. Tasks sem
  chamador (`reindex_one`, `reindex_all_task`, `recompute_one`) saíram.
- Colunas sem uso removidas (migrations): `Restaurant.origin`/`external_id`,
  `User.level`, `Address.geocoded_at`.
- `AbstractAudit.soft_delete()` substitui 6 cópias; `IsAuthorOrAdmin` herda de
  `IsRestaurantOwnerOrAdmin` (`owner_field`).
- 182 testes Django + 15 regressões verdes; schema OpenAPI válido.

## 2026-09-28 — testes finais de integração e segurança
- Stack inteiro testado sem Docker (Postgres+pgvector, Redis, shinzou e um
  Ollama falso determinístico) com o front em navegação E2E. Ver
  `final-tests/README.md`.
- Corrigido: troca de senha e encerrar conta agora **revogam todos os
  refresh tokens** (troca de senha devolve par novo); refresh de conta
  removida dava **500** → 401; **rate limit de login burlável** trocando o
  `X-Forwarded-For` → `NUM_PROXIES` (0 dev / 1 prod); busca com `query`
  não-texto dava 500 e `limit` inválido dava 503 → 400 (query ≤ 500
  caracteres, limit 1..50); recriar horário de dia removido dava 500
  (UniqueConstraint com linha soft-deleted) → reaproveita a linha; dono
  abrindo o próprio restaurante inflava `view_count` → não conta mais;
  recompute com `user_id` não numérico → 400.
- Contrato alterado: `POST /users/<id>/change-password/` responde
  `{detail, access, refresh}`.
- `final-tests/`: 16 testes de regressão (falham no código antigo, passam
  no novo), smoke de 67 checagens contra a API rodando, `fake_ollama.py`.
- 178 testes Django + 16 regressões + 6 do shinzou verdes.

## 2026-09-24
- Integração com o frontend (repo `front-end`, Next.js 16): mocks removidos,
  todas as telas falando com esta API.
- Novas rotas: `users/me/`, `users/logout/` (blacklist de refresh),
  `restaurants/mine/`, `restaurants/taxonomies/`, `restaurants/by-slug/<slug>/`,
  `restaurants/<id>/stats/` (métricas agregadas do dono), `api/health/`.
- Contratos alterados: login e register devolvem `{access, refresh, user}`
  (register já autentica; aceita `account_type` customer|owner e
  `allow_info`); listagens/busca/favoritos devolvem cards de restaurante
  (endereço público, `is_open_now`, `is_favorited`); busca devolve `match`
  (similaridade 0-100) e responde 503 para qualquer falha do shinzou; reviews
  expõem `author_name` (só primeiro nome). Listagem com filtros
  (`q`, taxonomias, `city`, `delivery`, `ordering`).
- LGPD: `GET /users/<id>/` de terceiros não expõe mais CPF/e-mail/telefone;
  `RestaurantView` por usuário e o recompute de afinidades só com
  `allow_info`; métrica anônima `Restaurant.view_count` para o dono.
- Regras: 1 review por usuário/restaurante; dono não avalia o próprio;
  score de afinidade limitado a 0..1; criar restaurante promove customer→owner.
- Produção: `DEBUG` default False, `SECRET_KEY`/`SHINZOU_SERVICE_TOKEN`
  obrigatórios, CORS/CSRF por env, JWT 15min/7d com rotação + blacklist,
  throttle da busca (30/min), gunicorn + whitenoise, container não-root,
  `docker-compose.prod.yml` com Caddy (HTTPS automático). Ver [[deploy]].
- `seed_demo`: 9 restaurantes de Marília/SP para demonstração.
- 178 testes Django + 6 do shinzou verdes.

## 2026-06-28
- Docs: criada a wiki do projeto em `docs/` no padrão LLM Wiki (index, log,
  architecture, modules, data-model, search-rag, security, infrastructure,
  frontend, backlog).
- Handoff frontend: drf-spectacular ligado (`/api/docs/`, `/api/schema/`), 8
  APIViews anotadas com `@extend_schema`, schema 0 erros.
- Postman `postman_collection.json` reconstruído (46 requests, 6 grupos).
- `API_MAP.md` escrito na raiz.
- Nova rota `PATCH /api/users/consent/` (toggle LGPD `allow_info`) + 5 testes.

## ~2026-06 (consolidado — antes da wiki)
- Auditoria completa pré-handoff: 12 achados corrigidos (CORS, paginação,
  token_type no shinzou, connection pool + DI, isolamento de reindex, clamp de
  limite, embed→503, retenção de histórico, TOCTOU em itens, busca JWT-only,
  service token constant-time). 138 testes + 6 do shinzou verdes, pyright 0.
- LGPD: campo `User.allow_info` (default false) gateando SearchHistory.
- Celery (worker + beat) para indexação/recompute assíncronos.
- Fase RAG completa: sinais → preferências → embeddings pgvector → shinzou
  (FastAPI) → ponte Django↔shinzou. Verificado fim-a-fim.
- Apps base: users (login por email, soft delete), restaurants (+ taxonomias,
  itens, reviews, favoritos, views), address (GenericForeignKey), preferences,
  embeddings.

> Convenção: ao mudar arquitetura/escopo, adicione uma linha datada aqui.
