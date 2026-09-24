# Log

Registro cronológico (append-only). Mais recente no topo.

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
