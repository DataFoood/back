# Backlog

Próximos passos. Genérico por ora — aprofundar adiante. Mais recente no topo,
agrupado por tema.

## Próximo foco — Mapeamento & descoberta de dados (insights)
Rotas de leitura analítica sobre os sinais já coletados (views, favoritos,
buscas, reviews, preferências). Objetivo: transformar dado bruto em insight pro
produto e pros donos de restaurante. Genérico por enquanto — detalhar depois.

Direções (a refinar):
- **Descoberta de tendências:** termos de busca mais frequentes, cozinhas/
  ambientes em alta, demanda sem oferta (buscas sem bom match).
- **Insight por restaurante (owner):** views ao longo do tempo, taxa de
  favoritar, distribuição de reviews, posição típica nos rankings de busca.
- **Insight de audiência:** perfis de afinidade agregados (respeitando LGPD —
  só dados de quem consentiu; preferir agregação/anonimização).
- **Métricas de busca:** qualidade do ranking, taxa de 503, latência do shinzou.
- **Mapa/geográfico:** densidade de restaurantes e demanda por região (usa
  Address lat/long).

Considerações ao construir:
- Acesso: separar o que é 🛡️ admin do que é 👤 owner (só o próprio restaurante).
- LGPD: dados pessoais só agregados/consentidos. Ver [[security]].
- Performance: evitar N+1; agregar no banco; cachear o que for caro.

## Pendências técnicas conhecidas (deferidas)
- **Overture Maps:** pipeline de import (campo `confidence`, choice de origin
  "overture", import DuckDB/GeoParquet, mapeamento de categorias, cron mensal,
  confidence → peso de ranking). Groundwork já existe (`origin`/`external_id`).
- **SearchHistory → ranking:** hoje só armazenado/exposto; ainda não realimenta
  o reranking do shinzou. Ver [[search-rag]].
- **Fallback de embedding:** quando o Ollama cai, a busca responde 503; falta
  estratégia de fallback (cache de query, índice texto, degradação graciosa).

## Saúde do projeto (base — feito)
Auditoria de segurança, paginação, RAG fim-a-fim, Celery, LGPD, docs de handoff
(Swagger + Postman + API_MAP) e esta wiki. Histórico em [[log]].
