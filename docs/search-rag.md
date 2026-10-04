# Search / RAG

Busca semântica fim-a-fim, dentro do Django (`embeddings/search.py`). O Ollama
só gera os vetores.

## Pipeline
```
POST /api/search/  {query, limit, lat?, lon?, radius_km?}   (restaurants.views.SearchView)
        │  valida query (≤ 500), limit (1..50), coordenadas; JWT do usuário
        ▼
embeddings.search.search(user, query, limit, origin, radius_km)
   1. embed: query → vetor via Ollama (nomic-embed-text, 768d)
   2. kNN: candidatos no pgvector por distância cosseno (CosineDistance), pool 50
   3. distância (haversine) até o endereço geocodificado de cada candidato;
      com radius_km, sai quem está fora do raio ou sem coordenada
   4. sinais: similaridade, afinidades do usuário, rating, proximidade
   5. rerank: z-score de cada sinal (desconhecido = neutro) → soma ponderada
   6. trunca em `limit` (default 15, máx 50)
        ▼
   SearchView hidrata os cards (ordem do ranking), conta impressões → front
```

## Indexação (offline, assíncrona)
Dado relevante muda (nome, descrição, itens, taxonomias) → signal marca
`Restaurant.embedding_stale=True`. O Celery reprocessa:
- `reindex-stale-hourly` (beat, de hora em hora) → só os stale.
- `manage.py reindex_restaurants [--all]` → sob demanda.

`reindex_restaurant`: monta o documento ([[modules#App `embeddings`|embeddings/documents.py]]),
embeda no Ollama, faz `update_or_create` do `RestaurantEmbedding`, zera o stale.
`reindex_all` isola cada item em try/except → um erro não derruba o lote.

## Ranking (z-score ponderado)
Três dimensões normalizadas por z-score (média 0, desvio 1; zera se σ=0) e
somadas com pesos:
- **semântico** — proximidade query↔restaurante.
- **preferência** — afinidade do usuário (cuisine/ambient/price).
- **review** — sinal de qualidade.
- **distância** — mais perto = melhor (entra negativa). Só quando o usuário manda
  `lat`/`lon`; restaurante sem coordenada fica neutro (z = 0).

A localização do usuário é usada só no request e descartada. A do restaurante
vem do geocoding do endereço (Nominatim/OSM, task Celery `geocode_address`,
1 req/s global; backfill: `manage.py geocode_addresses`).

Pesos lidos de `RankingWeight` (tabela, editável no admin), com fallback em
`DEFAULT_WEIGHTS`. `rank()` é função pura; testes em `embeddings/tests.py`.

## Preferências do usuário
`compute_user_preferences` agrega views (peso 1×count) + favoritos (peso 5),
normaliza por dimensão pelo máximo, pula linhas `is_manual`. Roda via Celery
(`recompute-preferences-daily`, 03:30; ou `manage.py recompute_preferences`).

## Falhas e tratamento
- Ollama fora → Django responde **503** (front mostra fallback; resto do
  app segue). Estratégia de fallback de embedding é item de [[backlog]].
- `query` vazio → **400**.

## LGPD no fluxo de busca
A query só é gravada em `SearchHistory` se a resposta foi 200 **e**
`user.allow_info=true`. Retenção: últimas 50 buscas por usuário. Ver
[[security]].

## Métricas do dono (app `analytics`)
Tabela fato `AccessStat`: contagem por restaurante × dia × hora × evento ×
faixa etária × célula — nada de usuário.
- **evento:** `impression` (apareceu num resultado exibido da busca), `view`
  (abriu o detalhe), `search_view` (abriu o detalhe vindo da busca = clique).
- **faixa etária:** só de quem deu consentimento (`allow_info`) e informou a
  data de nascimento; o resto é `unknown`.
- **célula:** ~1 km (coordenada arredondada em 2 casas) quando o front manda a
  localização; nula sem localização. Nome (bairro, cidade) por reverse
  geocoding, uma vez por célula (`GeoCell`).
- **k-anonimato (K=5):** o BI (`/api/analytics/restaurants/<id>/`) devolve
  `null` pra qualquer grupo com 1-4 acessos e tira do mapa células abaixo de K.
- `PlatformDailyStat`: buscas e falhas (503) por dia, pro painel admin.
- Demo: `manage.py seed_analytics_demo [--days 30] [--clear]` gera acessos
  fictícios ao redor dos restaurantes (só com `DEBUG=True`).
