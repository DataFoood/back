# Data Model

Modelos e relações. Tudo herda `AbstractAudit` (created_at, updated_at,
deleted_at) → **soft delete** universal.

## Soft delete
DELETE não apaga: seta `deleted_at`. O manager `objects` (via `ActiveManager`)
filtra deletados; `all_objects` enxerga tudo. Usuário deletado também perde
`is_active` → não loga mais. Ver [[security]].

## Diagrama de relações
```
User ──< RestaurantReview >── Restaurant
User ──< RestaurantFavorite >── Restaurant      (sinal forte, peso 5)
User ──< RestaurantView (count) >── Restaurant  (sinal fraco, peso 1)
User ──< SearchHistory                          (só se allow_info=true)
User ──< UserCuisine/Ambient/PriceAffinity      (derivado dos sinais)

Restaurant ──< RestaurantImage
Restaurant ──< BusinessHour (unique restaurant+day_week)
Restaurant ──< RestaurantItem (máx 6)
Restaurant ──1:1── RestaurantEmbedding (vector 768)
Restaurant >──< Cuisine / Ambient / ServiceModel / TargetAudience /
                PriceRange / BusinessModel / PhysicalFormat   (7 M2M)

Address ──(GenericForeignKey)──▶ Restaurant | User
```

## User
Login por email (`USERNAME_FIELD="email"`, sem username). Campos próprios: name,
cpf (unique, null), phone, birthday, gender, avatar/banner_url, role
(customer/owner/admin), level, **`allow_info`** (LGPD, default false). Detalhe
do consentimento em [[security]].

## Restaurant
Núcleo. Além de dados cadastrais:
- **7 taxonomias M2M** (lookup tables semeadas via data migration): cuisines,
  ambients, service_models, target_audiences, price_ranges, business_models,
  physical_formats.
- **7 flags de canal de venda**: has_dine_in, has_delivery, has_take_out,
  has_drive_thru, has_reservation, accepts_vale_refeicao, accepts_online_order.
- `average_rating` / `total_reviews`: **cache denormalizado** das reviews
  (recalculado por `recalc_rating()`; não é fonte da verdade).
- `origin` (manual/google) + `external_id` (unique) — anti-duplicata em import.
- `embedding_stale` (default true) — marca pendência de reindexação.

## Sinais de preferência (alimentam a busca)
| Modelo | Sinal | Peso |
|---|---|---|
| `RestaurantView` | viu o restaurante (count agregado) | fraco (1×count) |
| `RestaurantFavorite` | favoritou | forte (5) |
| `RestaurantItem` | pratos (até 6) — entram no embedding e no match por comida | — |

`compute_user_preferences` agrega esses sinais em afinidades normalizadas por
dimensão (cuisine/ambient/price). Linhas editadas à mão viram `is_manual=true` e
o recompute não as sobrescreve. Ver [[search-rag]].

## Embeddings
`RestaurantEmbedding` (OneToOne) guarda o vetor (`VectorField(768)`), o
documento-texto usado e o modelo. Distância por operador `<=>` (cosseno) do
pgvector. O shinzou lê essa tabela direto.

## Taxonomias (lookup)
Todas herdam `BaseLookup` (name unique, ordenado). Semeadas via data migration;
o front geralmente só lê pra montar filtros.

## Address
Polimórfico: `content_type` + `object_id` apontam pra Restaurant **ou** User. A
API recebe `entity_type` (`"restaurant"`/`"user"`) e resolve o ContentType.
