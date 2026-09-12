# Frontend — estrutura de páginas

Sugestão de telas, features por tela, rotas consumidas e nível de acesso.
Contrato exato das rotas: [../API_MAP.md](../API_MAP.md) + Swagger
(`/api/docs/`). Acesso: 🌐 público · 🔑 logado · 👤 dono · 🛡️ admin.

## Mapa de navegação
```
Pública            Autenticada                 Admin
─────────          ───────────                 ─────
Landing            Busca semântica             Dashboard admin
Login/Cadastro     Detalhe restaurante         Moderação restaurantes
Lista/Explorar     Favoritos                   Jobs (reindex/recompute)
Detalhe (read)     Perfil + consentimento      Usuários
                   Minhas preferências
                   (Owner) Gerir restaurante
```

## Páginas

### 1. Landing 🌐
Apresentação + CTA. Pode listar destaques.
- `GET /api/restaurants/` (paginado).

### 2. Login / Cadastro 🌐
- `POST /api/users/register/` — cadastro.
- `POST /api/users/login/` — guarda `access`+`refresh`.
- `POST /api/users/login/refresh/` — renova `access` ao expirar.
- Tratar **429** (rate limit: login 5/min, register 10/h).

### 3. Explorar / Lista 🌐
Listagem paginada + filtros por taxonomia.
- `GET /api/restaurants/?page=&page_size=` (máx 50).
- Filtros usam as taxonomias (cuisines/ambients/price_ranges...).

### 4. Busca semântica ⭐ 🔑
Campo de busca em linguagem natural.
- `POST /api/search/` `{query, limit}`.
- Tratar **503** (busca indisponível → fallback amigável, resto do app segue).
- Tratar **400** (query vazia).

### 5. Detalhe do restaurante 🌐 ler / 🔑 interagir
- `GET /api/restaurants/<id>/` (registra view se logado).
- `GET .../items/`, `.../reviews/`, `.../images/`, `.../hours/`.
- 🔑 `POST/DELETE .../favorite/` (idempotente).
- 🔑 `POST .../reviews/` (criar review).

### 6. Favoritos 🔑
- `GET /api/restaurants/favorites/`.

### 7. Perfil + Consentimento 🔑 / 👤
- `GET /api/users/<id>/` (detalhe).
- 👤 `PATCH /api/users/<id>/` (editar perfil).
- 🔑 `PATCH /api/users/consent/` — **toggle LGPD** `allow_info`.
- 🔑 `POST /api/users/<id>/change-password/`.
- 👤 `DELETE /api/users/<id>/delete/` (encerrar conta, soft).

### 8. Minhas preferências 🔑
Afinidades calculadas + ajuste manual.
- `GET /api/preferences/` (cuisines/ambients/price_ranges).
- `GET /api/preferences/searches/` (histórico — só se consentiu).
- `PATCH /api/preferences/{cuisines|ambients|prices}/<id>/` (edita → manual).

### 9. Gerir restaurante (Owner) 👤
CRUD do próprio restaurante e filhos.
- `POST /api/restaurants/`, `PATCH/DELETE /api/restaurants/<id>/`.
- `.../items/` (**máx 6**), `.../images/`, `.../hours/`, endereços.
- Endereço: `POST /api/addresses/` com `entity_type:"restaurant"` + `object_id`.

### 10. Admin 🛡️
- `GET /api/users/` e `/api/users/removed/` (paginado).
- `POST /api/preferences/recompute/` — recálculo async (**202**).
- `POST /api/embeddings/reindex/` — reindexação async (**202**).
- Jobs retornam `task_id`; rodam no worker em background.

## Padrões pro front lembrar
- **Auth:** Bearer access em tudo logado; renovar via refresh; refresh **não**
  serve como access.
- **Paginação:** `{count, next, previous, results}` nas listas grandes.
- **Erros de validação:** `{campo: [msg]}` (400).
- **Idempotência:** favoritar 2× não duplica (201 → 200).
- **LGPD:** sem consentimento, histórico não aparece — esconder a aba ou
  mostrar CTA de ativar.

Próximas rotas (insights/descoberta) em [[backlog]].
