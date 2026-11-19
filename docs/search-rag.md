# Search / RAG

Busca semântica fim-a-fim. O front fala só com o Django; o **shinzou** (FastAPI,
interno) faz a busca vetorial. A explicação textual opcional é gerada pelo
Django diretamente no Ollama, conforme a seção abaixo.

O frontend do chat usa agora o [assistente conversacional](conversation.md), em
`POST /api/chats/respond/`, com filtros acumulados, contexto por plano e seleções
persistidas. Este documento descreve a busca legada `/api/search/`, preservada.

## Explicação local opcional

`CHAT_GENERATION_ENABLED=True` acrescenta `answer` a `POST /api/search/`.
O padrão é desabilitado. `answer` é texto ou `null` quando desabilitado,
sem candidatos ou quando a geração falha; os cards permanecem disponíveis.
Não há mudança no corpo da requisição nem migração de banco.

Para a demonstração na t3.small, usar `SEMANTIC_SEARCH_ENABLED=False` e
`CHAT_MODEL=qwen3:0.6b`: recuperação textual e explicação no mesmo backend,
sem carregar embeddings para cada busca. Só ativar após disponibilizar o
modelo, configurar limites no Ollama e validar o cliente que lê `answer`.
Não editar apenas o `.env`: processos existentes precisam receber as novas
variáveis. Esta alteração local ainda não configura ou publica a VPS.

`restaurants/generation.py` envia somente a consulta atual e nome, descrição
curta e até duas tags de cozinha/ambiente/preço dos três primeiros cards.
Não envia conta, documentos, favoritos, histórico ou contatos; a personalização
por plano pertence ao endpoint conversacional. Usa `httpx` já instalado, contexto 1024,
até 120 tokens de saída, uma thread, sem thinking e keep-alive de dois minutos.
Timeout de leitura de 30 s e conexão de 3 s; não há retentativa automática.

A resposta do modelo é validada por formato, tamanho e término natural;
texto vazio/truncado, JSON inválido e erros HTTP retornam `answer: null`.
O texto ainda pode conter erros factuais: validação estrutural e instruções
no prompt não garantem relevância ou precisão. Esta etapa não permite ao
modelo executar ferramentas, consultar URLs ou alterar registros.

Testes sem banco: `cd dtfd && uv run python manage.py test restaurants.test_generation`.
O Ollama é simulado nesses testes; a prova real inicial está em
`tasks/vps-baseline.md` e não substitui o ensaio completo com catálogo real.

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
- Falha do shinzou ou busca semântica desativada → Django responde **200**
  com recuperação textual e filtros (`mode: text`, `match: null`, `notice`).
- Falha da explicação local → mantém os resultados e retorna `answer: null`.
- `query` vazio → **400**.

## LGPD no fluxo de busca
No caminho semântico bem-sucedido, a query só é gravada em `SearchHistory`
com `user.allow_info=true`. Retenção: últimas 50 buscas por usuário. O caminho
textual não grava esse histórico; a geração opcional não altera essa regra.
Ver [[security]].
