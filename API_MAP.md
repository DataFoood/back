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

Login por **email** (não tem username). Fluxo:

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
um par novo — guarde-o, senão a sessão atual cai no próximo refresh.

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

Listagens (`users`, `restaurants`) paginam com **10 itens/página**:

```
GET /api/restaurants/?page=2&page_size=20      # page_size máx = 50
```

Resposta:
```json
{ "count": 137, "next": "...?page=3", "previous": "...?page=1", "results": [ ... ] }
```

Listagens aninhadas curtas (items, reviews, images, hours de um restaurante;
preferences; searches) **não** paginam — retornam array direto.

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
| GET | `` (lista) | 🛡️ | paginado; `?q=` (nome/e-mail), `?role=` |
| GET | `removed/` | 🛡️ | soft-deleted, paginado |
| GET | `<id>/` | 🔑 | completo p/ dono/admin; terceiros veem só `id, name, avatar_url, banner_url, created_at` |
| PATCH | `<id>/` | 👤 | edita perfil |
| PATCH | `consent/` | 🔑 | **LGPD** — liga/desliga `allow_info` do próprio user |
| POST | `<id>/change-password/` | 🔑 (só o próprio) | exige senha atual; revoga todas as sessões e responde `{detail, access, refresh}` |
| DELETE | `<id>/delete/` | 👤 | soft delete (bloqueia login na hora) |
| PATCH | `<id>/admin/` | 🛡️ | `{role?, is_active?}` — `role=admin` dá `is_staff`; `is_active=true` reativa removido; `false` derruba sessões. Não vale pra si mesmo |

### Restaurants — `/api/restaurants/`
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| GET | `` | 🌐 | lista paginada de **cards**; filtros `q`, `cuisine`, `ambient`, `price_range`, `service_model`, `target_audience` (ids, vírgula), `city`, `delivery=true`, `ordering=recent\|rating\|name\|distance`; `lat`+`lon` (visitante, não guardado) preenchem `distance_km` e liberam `ordering=distance` e `radius_km` |
| POST | `` | 🔑 | cria (vira owner; customer → role owner) |
| GET | `mine/` | 🔑 | meus restaurantes (cards, sem paginação) |
| GET | `taxonomies/` | 🌐 | as 7 taxonomias `{cuisines: [{id,name}], ...}` |
| GET | `by-slug/<slug>/` | 🌐 | detalhe pelo slug (mesmo payload do `<id>/`) |
| GET | `<id>/` | 🌐 | detalhe; soma `view_count` e a visita do dia; `?src=search` conta clique vindo da busca; `?lat=&lon=` conta a visita na região (~1 km). View por usuário só com consentimento |
| GET | `<id>/stats/` | 👤 (owner) | métricas agregadas (30 dias): visitas, aparições na busca, cliques vindos da busca + CTR, favoritos, reviews, série diária, top 10 regiões das visitas, distribuição de notas |
| GET | `admin/` | 🛡️ | moderação: todos, inclusive removidos; `?q=`, `?deleted=true\|false` |
| POST | `<id>/restore/` | 🛡️ | desfaz soft delete |
| POST | `<id>/reindex/` | 🛡️ | regera o embedding (async, **202**) |
| PATCH/DELETE | `<id>/` | 👤 (owner) | DELETE = soft |
| POST/DELETE | `<id>/favorite/` | 🔑 | favoritar (idempotente) / desfavoritar |
| GET | `favorites/` | 🔑 | meus favoritos `[{id, restaurant: <card>, created_at}]` |
| GET/POST | `<id>/items/` | 🌐 ler / 👤 escrever | **máx 30 itens** |
| ../PATCH/DELETE | `<id>/items/<id>/` | 👤 | |
| GET/POST | `<id>/reviews/` | 🌐 ler / 🔑 escrever | autor fica dono; 1 por usuário; dono não avalia o próprio (400) |
| ../PATCH/DELETE | `<id>/reviews/<id>/` | 👤 (autor) | |
| GET/POST | `<id>/images/` | 🌐 ler / 👤 escrever | |
| GET/POST | `<id>/promotions/` | 🌐 ler / 👤 escrever | **promoção relâmpago**: `{title?, starts_at?, ends_at, items: [{item, discount_type: percent\|amount, discount_value}]}`. Máx 24 h, sem sobreposição; % até 90; valor < preço. Responde com `final_price` por item |
| DELETE | `<id>/promotions/<id>/` | 👤 | encerra agora (fica no histórico) |
| GET/POST | `<id>/hours/` | 🌐 ler / 👤 escrever | `meta_interval` JSON |

Restaurante carrega 7 taxonomias M2M (cuisines, ambients, service_models,
target_audiences, price_ranges, business_models, physical_formats) + 7 flags de
canal de venda (`has_dine_in`, `has_delivery`, ...). `average_rating`/
`total_reviews` são cache denormalizado (recalculados das reviews; read-only).

**Card** (listas, busca, favoritos): `id, name, slug, description, cover_image,
average_rating, total_reviews, cuisines, ambients, price_ranges, address,
is_open_now, is_favorited, has_delivery, has_reservation, distance_km, promotion`.
`promotion` (card) = resumo da promoção relâmpago ativa `{id, title, ends_at, items_count, max_discount_percent}` ou `null`; no detalhe vem completa, com `items[].final_price`. Catálogo aceita `?promo=true`. O detalhe tem tudo
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

Endereço de **restaurante** é geocodificado sozinho (Nominatim/OSM, em
background) quando criado ou quando a rua/cidade/CEP muda — `latitude`/`longitude`
aparecem alguns segundos depois. Mandar `latitude` explícita desliga isso.
Endereço de usuário nunca sai pro Nominatim.

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
| GET/PATCH | `weights/` | 🛡️ | pesos do ranking `{semantic, preference, review, distance}` (0..5); PATCH parcial |

### Analytics — `/api/analytics/`
| Método | Rota | Acesso | Nota |
|---|---|---|---|
| GET | `platform/` | 🛡️ | contas por papel, restaurantes (removidos, sem localização, indexação pendente), buscas/falhas e visitas por dia (30 dias) |
| GET | `restaurants/<id>/` | 👤 (owner) | BI do dono: `?days=7\|30\|90` `?metric=views\|impressions\|clicks` `?age=40-59,60+` `?hour_from=&hour_to=` (cruza meia-noite). Devolve totais, por hora, por dia, por faixa etária, células do mapa e ranking de regiões. Grupos com 1-4 acessos saem `null` (k-anonimato, K=5) |

### Search — `/api/search/` ⭐
| Método | Rota | Acesso |
|---|---|---|
| POST | `` | 🔑 |

```json
// request
{ "query": "lugar tranquilo pra comer feijoada", "limit": 15, "lat": -22.21, "lon": -49.94, "radius_km": 5 }
```
Body: `query` obrigatório (texto, **máx 500 caracteres**); `limit` opcional
(inteiro 1..50, default 15). `lat`+`lon` opcionais (juntos): localização do
usuário, usada **só neste request** — favorece os mais próximos (peso
`distance`). `radius_km` (0..100, exige lat/lon) corta quem está fora do raio
ou sem coordenada. Fora disso → 400.
Rate limit: 30/min por usuário (`SEARCH_RATE`).
```json
// response
{ "results": [ { "restaurant": { /* card */ }, "score": 1.42, "match": 87, "distance_km": 0.8 } ] }
```
`match` = similaridade semântica (0-100) — é o "% match" da UI. `score` só
ordena.

---

## 4. Busca semântica — como funciona por trás

O frontend fala **só com o Django** (`:8000`). `POST /api/search/` roda a busca
no próprio Django; o Ollama (interno) só gera o vetor da query.

Pipeline: query → embedding (Ollama) → kNN no pgvector → reranking ponderado
(semântico + preferências do usuário + reviews) → top N.

Erros que o front deve tratar:
- **503** — serviço de busca indisponível (Ollama fora ou erro
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

---

## 7. Subir o ambiente

```bash
docker compose up -d --build      # sobe db, redis, ollama, web, worker, beat
```

Django em `http://localhost:8000`. Swagger em `/api/docs/`. A 1ª subida puxa o
modelo de embedding no Ollama (pode demorar). Só a porta 8000 (Django) é pra
consumo do front.
