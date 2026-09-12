# Search / RAG

Busca semântica fim-a-fim. O front fala só com o Django; o **shinzou** (FastAPI,
interno) faz o trabalho de IA.

## Pipeline
```
POST /api/search/  {query, limit}
        │  Django (ponte): + X-Service-Token + Bearer JWT do usuário
        ▼
shinzou /search
   1. auth: valida service token (constant-time) E o JWT (token_type=access)
   2. embed: query → vetor via Ollama (nomic-embed-text, 768d)
   3. kNN: candidatos no pgvector por distância cosseno (<=>), pool ~50
   4. sinais: carrega afinidades do usuário + reviews dos candidatos
   5. rerank: z-score de cada dimensão → soma ponderada
   6. trunca em `limit` (default 15, máx 50)
        ▼
   ranking de restaurantes  → Django  → front
```

## Indexação (offline, assíncrona)
Dado relevante muda (nome, descrição, itens, taxonomias) → signal marca
`Restaurant.embedding_stale=True`. O Celery reprocessa:
- `reindex-stale-hourly` (beat, de hora em hora) → só os stale.
- `reindex/` (admin, sob demanda) → stale ou todos.

`reindex_restaurant`: monta o documento ([[modules#App `embeddings`|embeddings/documents.py]]),
embeda no Ollama, faz `update_or_create` do `RestaurantEmbedding`, zera o stale.
`reindex_all` isola cada item em try/except → um erro não derruba o lote.

## Ranking (z-score ponderado)
Três dimensões normalizadas por z-score (média 0, desvio 1; zera se σ=0) e
somadas com pesos:
- **semântico** — proximidade query↔restaurante.
- **preferência** — afinidade do usuário (cuisine/ambient/price).
- **review** — sinal de qualidade.

Pesos lidos de `RankingWeight` (tabela), com fallback nas constantes do
`shinzou/config.py`. Funções puras e testadas em `shinzou/tests/test_ranking.py`.

## Preferências do usuário
`compute_user_preferences` agrega views (peso 1×count) + favoritos (peso 5),
normaliza por dimensão pelo máximo, pula linhas `is_manual`. Roda via Celery
(`recompute-preferences-daily`, 03:30; ou `recompute/` admin sob demanda).

## Acoplamento Django ↔ shinzou
- **Banco compartilhado:** shinzou lê o mesmo Postgres por SQL cru (psycopg2,
  `ThreadedConnectionPool` + dependência `get_db()`). Não usa o ORM.
- **Auth de 2 camadas:** `X-Service-Token` (segredo de serviço) + Bearer JWT do
  usuário, validado com a **mesma** `SECRET_KEY` (HS256). Ver [[security]].

## Falhas e tratamento
- Ollama/shinzou fora → Django responde **503** (front mostra fallback; resto do
  app segue). Estratégia de fallback de embedding é item de [[backlog]].
- `query` vazio → **400**.

## LGPD no fluxo de busca
A query só é gravada em `SearchHistory` se a resposta foi 200 **e**
`user.allow_info=true`. Retenção: últimas 50 buscas por usuário. Ver
[[security]].
