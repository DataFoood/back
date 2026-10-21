# DataFood — API Map (handoff frontend)

Mapa narrativo da API. Para o contrato vivo e interativo, use o **Swagger**:

| Recurso | URL |
|---|---|
| Swagger UI | `http://localhost:8000/api/docs/` |
| Schema OpenAPI (YAML) | `http://localhost:8000/api/schema/` |
| Postman | `postman_collection.json` (raiz do repo) |

O Swagger é gerado do código (drf-spectacular) → sempre sincronizado com a
implementação. Este arquivo é o resumo de alto nível; em divergência, o Swagger
vence.

---

## 1. Autenticação (JWT)

Login por **email** (não tem username). Dois jeitos de carregar a sessão,
com o mesmo JWT por trás:

| Cliente | Como | Tokens |
|---|---|---|
| **Navegador (o front)** | manda `X-Requested-With: datafood` + `credentials: include` | em **cookies HttpOnly** (`datafood_access`, path `/`; `datafood_refresh`, path `/api/users/`). Nunca no corpo — o JS não os vê |
| API (Postman, Swagger, scripts) | sem o cabeçalho | no corpo; mande `Authorization: Bearer <access>` |

Navegador, em resumo: login/cadastro respondem `{user, access_expires_in}` e
gravam os cookies; o front chama `POST /api/users/login/refresh/` com corpo
vazio antes do access vencer (e ao receber 401) — o back lê o refresh do
cookie, rotaciona e grava os novos; `POST /api/users/logout/` blacklista e
apaga os cookies. **CSRF:** escrita autenticada por cookie exige o cabeçalho
`X-Requested-With` (403 sem ele); site de terceiro não consegue mandá-lo sem
passar pelo CORS, que só libera a origem do front. Cookies `SameSite=Lax`,
`Secure` em produção.

Fluxo da API (Bearer):

1. `POST /api/users/register/` — cadastro aberto (rate limit 10/hora por IP).
   Body: `name, email, password, confirm_password` + opcionais `cpf, phone,
   account_type ("customer"|"owner"), allow_info`. **Já autentica**: responde
   `{access, refresh, user}` (201).
2. `POST /api/users/login/` — `{email, password}` → `{access, refresh, user}`
   (rate limit 5/min, anti brute-force).
3. Mandar o access em todo request protegido:
   `Authorization: Bearer <access>` (vida: 15 min).
4. `POST /api/users/login/refresh/` — `{refresh}` → `{access, refresh}`. O
   refresh **rotaciona**: guarde o novo; o antigo é invalidado. Conta
   removida/inativa → 401.
5. `POST /api/users/logout/` — `{refresh}` → 204 (refresh vai pra blacklist).
6. `GET /api/users/me/` — usuário logado (restaurar sessão).

**Segurança:** o backend distingue access de refresh (claim `token_type`). Um
refresh token **não** é aceito como credencial em rotas protegidas → 401. Não
tente reusar refresh como access.

**Revogação:** trocar a senha ou encerrar a conta invalida **todos** os
refresh tokens do usuário (todas as sessões). A troca de senha responde com
um par novo (no navegador, em cookie) — guarde-o, senão a sessão atual cai no
próximo refresh. Encerrar a conta apaga também as conversas do chat e os
cookies.

No Postman, rode **"Login (salva tokens)"** primeiro: um script guarda
`access_token`/`refresh_token` nas variáveis da coleção automaticamente.

### Níveis de acesso
| Nível | Quem | Como o front sabe |
|---|---|---|
| Público (sem token) | qualquer um | rotas marcadas *aberto* abaixo |
| Autenticado | qualquer usuário logado | tem `access` válido |
| Dono ou admin | dono do recurso OU `is_staff` | 403 se não for |
| Admin | só `is_staff=true` | 403 caso contrário |

---

## 2. Paginação

**Toda** listagem pagina igual (`DEFAULT_PAGINATION_CLASS` =
`utils.pagination.DefaultPagination`), **10 itens/página** por padrão:

```
GET /api/restaurants/?page=2&page_size=20      # page_size máx = 50
```

Resposta:
```json
{ "count": 137, "next": "...?page=3", "previous": "...?page=1", "results": [ ... ] }
```

Vale para users, restaurants, mine, favorites, items/reviews/images/hours de
um restaurante, addresses, searches, promoções (gestão e vitrine) e chats. O
detalhe do restaurante **não** embute mais as avaliações (lista sem limite):
traz `has_reviewed` e as avaliações vêm de `GET .../reviews/` paginado.
Não paginam só respostas que não são listas: taxonomias (dicionário),
afinidades (`/api/preferences/`, 3 dimensões) e a busca semântica (top N).

---

## 3. Rotas por domínio

> Legenda de acesso: 🌐 aberto · 🔑 autenticado · 👤 dono/admin · 🛡️ admin

### Users — `/api/users/`
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| POST | `register/` | 🌐 | rate limit 10/h |
| POST | `login/` | 🌐 | rate limit 5/min; retorna access+refresh |
| POST | `login/refresh/` | 🌐 | renova access (rotaciona refresh) |
| POST | `logout/` | 🌐 | invalida o refresh |
| GET/PATCH | `me/` | 🔑 | perfil do logado |
| GET | `` (lista) | 🛡️ | paginado |
| GET | `removed/` | 🛡️ | soft-deleted, paginado |
| GET | `<id>/` | 🔑 | completo p/ dono/admin; terceiros veem só `id, name, avatar_url, banner_url, created_at` |
| PATCH | `<id>/` | 👤 | edita perfil |
| PATCH | `consent/` | 🔑 | **LGPD** — liga/desliga `allow_info` do próprio user |
| POST | `<id>/change-password/` | 🔑 (só o próprio) | exige senha atual; revoga todas as sessões e responde `{detail, access, refresh}` |
| DELETE | `<id>/delete/` | 👤 | soft delete (bloqueia login na hora) |

### Restaurants — `/api/restaurants/`
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| GET | `` | 🌐 | lista paginada de **cards**; filtros `q`, `cuisine`, `ambient`, `price_range`, `service_model`, `target_audience` (ids, vírgula), `city`, `delivery=true`, `ordering=recent\|rating\|name` |
| POST | `` | 🔑 | cria (vira owner; customer → role owner) |
| GET | `mine/` | 🔑 | meus restaurantes (cards, sem paginação) |
| GET | `taxonomies/` | 🌐 | as 7 taxonomias `{cuisines: [{id,name}], ...}` |
| GET | `by-slug/<slug>/` | 🌐 | detalhe pelo slug (mesmo payload do `<id>/`) |
| GET | `<id>/` | 🌐 | detalhe; soma `view_count`; view por usuário só com consentimento |
| GET | `<id>/stats/` | 👤 (owner) | métricas agregadas: views, favoritos, reviews, série 30 dias, distribuição de notas |
| PATCH/DELETE | `<id>/` | 👤 (owner) | DELETE = soft |
| POST/DELETE | `<id>/favorite/` | 🔑 | favoritar (idempotente) / desfavoritar |
| GET | `favorites/` | 🔑 | meus favoritos `[{id, restaurant: <card>, created_at}]` |
| GET/POST | `<id>/items/` | 🌐 ler / 👤 escrever | **máx 6 itens** |
| ../PATCH/DELETE | `<id>/items/<id>/` | 👤 | |
| GET/POST | `<id>/reviews/` | 🌐 ler / 🔑 escrever | autor fica dono; 1 por usuário; dono não avalia o próprio (400) |
| ../PATCH/DELETE | `<id>/reviews/<id>/` | 👤 (autor) | |
| GET/POST | `<id>/images/` | 🌐 ler / 👤 escrever | |
| GET/POST | `<id>/hours/` | 🌐 ler / 👤 escrever | `meta_interval` JSON |

Restaurante carrega 7 taxonomias M2M (cuisines, ambients, service_models,
target_audiences, price_ranges, business_models, physical_formats) + 7 flags de
canal de venda (`has_dine_in`, `has_delivery`, ...). `average_rating`/
`total_reviews` são cache denormalizado (recalculados das reviews; read-only).

**Card** (listas, busca, favoritos): `id, name, slug, description, cover_image,
average_rating, total_reviews, cuisines, ambients, price_ranges, address,
is_open_now, is_favorited, has_delivery, has_reservation`. O detalhe tem tudo
isso + items, reviews (com `author_name`), images, business_hours e demais
taxonomias/canais. `address` é o endereço **público** do restaurante (ou
`null`); `is_open_now` é `null` se não há horários cadastrados.

### Addresses — `/api/addresses/`
GenericForeignKey: um endereço aponta pra um **restaurant** ou **user**.
No POST mande `entity_type` (`"restaurant"`|`"user"`) + `object_id`.
| Método | Rota | Acesso |
|---|---|---|
| GET/POST | `` | 👤 (dono da entidade) |
| GET/PATCH/DELETE | `<id>/` | 👤 |

### Preferences — `/api/preferences/`
Afinidades do usuário em 3 dimensões (cuisine, ambient, price), calculadas dos
sinais (views + favoritos). Editar uma afinidade marca `is_manual=true` → o
recompute automático **para de sobrescrever** aquela linha.
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| GET | `` | 🔑 | minhas afinidades (3 listas) |
| GET | `searches/` | 🔑 | buscas recentes (últimas 50) |
| PATCH | `cuisines/<id>/` | 🔑 | edita score → manual |
| PATCH | `ambients/<id>/` | 🔑 | |
| PATCH | `prices/<id>/` | 🔑 | |
| POST | `recompute/` | 🛡️ | async (Celery); `{user_id}` ou todos; **202** |

### Embeddings — `/api/embeddings/`
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| POST | `reindex/` | 🛡️ | async; `{all: bool}` (default só stale); **202** |

### Promotions — mensageiros (Telegram, e-mail, WhatsApp)
Gestão aninhada no restaurante — `/api/restaurants/<restaurant_pk>/promotions/`:
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| GET/POST | `` | 👤 dono/admin | lista paginada (com `stats` por status de entrega) / cria **rascunho** |
| GET | `active/` | 🌐 | vitrine paginada: enviadas e dentro da validade, sem dados de envio |
| GET | `audience/` | 👤 | `{favorites, opted_in, telegram, email, telegram_configured}` (só contagens) |
| GET/PATCH/DELETE | `<id>/` | 👤 | editar só em `draft`/`scheduled`; DELETE = soft (sai da vitrine) |
| POST | `<id>/send/` | 👤 | `{}` envia agora (**202**, worker); `{scheduled_for}` agenda (200, 1 min–30 dias) |
| POST | `<id>/unschedule/` | 👤 | agendada → rascunho |

Cada promoção traz `share_text`, `whatsapp_url` (`wa.me/?text=…`) e
`public_url`. Limites: `PROMOTIONS_MAX_PER_DAY` por restaurante (400 com
`detail`) e `PROMOTIONS_USER_DAILY_CAP` por pessoa/24h (entrega `skipped`).

Cliente e operação — `/api/promotions/`:
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| GET/PATCH | `preferences/` | 🔑 | `promotions_opt_in`, `channel_email`, `channel_telegram`; lê `telegram_linked`, `opted_in_at` |
| POST/DELETE | `preferences/telegram/` | 🔑 | POST → `{url, expires_at}` (deep link do bot, 15 min; **503** sem bot); DELETE desvincula |
| POST | `unsubscribe/` | 🌐 | `{token}` do e-mail → desliga o opt-in (20/h por IP) |
| GET | `infra-suggestion/` | 🛡️ | projeção do fim de semana × capacidade local — números da plataforma inteira, só admin ([docs/weekend-infra.md](docs/weekend-infra.md)) |

Recebe promoção só quem **favoritou o restaurante e deu opt-in**. Detalhes
em [docs/promotions.md](docs/promotions.md).

### Chats — `/api/chats/` (conversas da busca, na conta)
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| GET/POST | `` | 🔑 | lista paginada sem mensagens (`?q=` no título) / cria `{title, messages}` |
| GET/PATCH/DELETE | `<id>/` | 🔑 (só as próprias; outras → 404) | DELETE apaga de verdade |

`messages`: lista de `{role: "user"|"assistant", ...}` (até 200, 256 KB). São
mantidas as 50 mais recentes por conta; encerrar a conta apaga todas.

### Search — `/api/search/` ⭐
| Método | Rota | Acesso |
|---|---|---|
| POST | `` | 🔑 (só JWT) |

```json
// request
{ "query": "lugar tranquilo pra comer feijoada", "limit": 15 }
```
Body: `query` obrigatório (texto, **máx 500 caracteres**); `limit` opcional
(inteiro 1..50, default 15). Fora disso → 400.
Rate limit: 30/min por usuário (`SEARCH_RATE`).
```json
// response
{ "results": [ { "restaurant": { /* card */ }, "score": 1.42, "match": 87 } ] }
```
`match` = similaridade semântica (0-100) — é o "% match" da UI. `score` só
ordena.

---

## 4. Busca semântica — como funciona por trás

O frontend fala **só com o Django** (`:8000`). A IA de busca roda num serviço
interno separado (**shinzou**, FastAPI `:8001`) que **não é exposto**
publicamente. `POST /api/search/` é uma ponte: o Django repassa a query ao
shinzou com um service-token + o JWT do usuário, recebe o ranking e devolve.

Pipeline: query → embedding (Ollama) → kNN no pgvector → reranking ponderado
(semântico + preferências do usuário + reviews) → top N.

Erros que o front deve tratar:
- **503** — serviço de busca indisponível (shinzou/Ollama fora ou erro
  interno). Mostrar fallback amigável; o restante do app continua funcionando.
- **429** — muitas buscas seguidas.
- **400** — `query` vazio/não-texto/> 500 caracteres ou `limit` inválido.

---

## 5. LGPD — consentimento (`allow_info`)

Todo usuário tem `allow_info` (boolean, **default `false`**). O histórico de
busca (SearchHistory) e os sinais de preferência só são gravados **se o usuário
consentiu**. Sem consentimento, a busca funciona normalmente, mas nada é
persistido sobre ela.

O front deve oferecer um toggle de consentimento → `PATCH /api/users/consent/`
com `{ "allow_info": true|false }`. O campo também aparece (read no detalhe,
write no update) no perfil.

---

## 6. Padrões transversais

- **Soft delete:** DELETE não apaga; marca `deleted_at`. Recursos deletados
  somem das listagens normais. Usuário deletado não consegue mais logar.
- **Datas:** ISO 8601, timezone `America/Sao_Paulo`.
- **Erros de validação:** DRF padrão → `{ "campo": ["mensagem"] }` (400).
- **CORS:** dev libera `localhost`/`127.0.0.1` nas portas 3000-3002 e
  5000-5002; produção usa `CORS_ALLOWED_ORIGINS`.
- **Health:** `GET /api/health/` → `{"status": "ok", "db": true}`.
- **Idempotência:** favoritar duas vezes não duplica (201 na 1ª, 200 depois).
- **202 Accepted:** rotas admin de recompute/reindex são assíncronas — retornam
  `task_id`; o trabalho roda no worker Celery em background.

---

## 7. Subir o ambiente

```bash
docker compose up -d --build      # sobe db, redis, ollama, web, worker, beat, shinzou
```

Django em `http://localhost:8000`. Swagger em `/api/docs/`. A 1ª subida puxa o
modelo de embedding no Ollama (pode demorar). Só a porta 8000 (Django) é pra
consumo do front; o shinzou (8001) é interno.
