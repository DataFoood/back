# Log

Registro cronológico (append-only). Mais recente no topo.

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
