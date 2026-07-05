# Index

Catálogo da wiki do DataFood. Backend Django/DRF de descoberta de restaurantes
com busca semântica (RAG).

## Base — estrutura do projeto
- [[architecture]] — visão geral, serviços, fluxo de request.
- [[modules]] — apps Django + serviço shinzou, arquivo por arquivo.
- [[data-model]] — modelos, relações, soft delete, sinais.
- [[search-rag]] — pipeline de busca semântica fim-a-fim.
- [[security]] — JWT, permissões, CORS, throttle, LGPD.
- [[infrastructure]] — Docker, serviços, portas, env.

## Contrato da API
- [../API_MAP.md](../API_MAP.md) — mapa narrativo de rotas + acesso.
- Swagger UI: `http://localhost:8000/api/docs/` (gerado do código).
- Postman: [../postman_collection.json](../postman_collection.json).

## Frontend
- [[frontend]] — páginas recomendadas, features, rotas, acesso.

## Planejamento
- [[backlog]] — próximos passos.
- [[log]] — registro cronológico.

## Categorias rápidas
| Quero entender... | Vá para |
|---|---|
| Como o sistema se divide em serviços | [[architecture]] |
| O que cada app/arquivo faz | [[modules]] |
| As tabelas e como se relacionam | [[data-model]] |
| Como a busca por IA funciona | [[search-rag]] |
| Como autenticação/permissão funcionam | [[security]] |
| Como subir o ambiente | [[infrastructure]] |
| Que telas o front precisa | [[frontend]] |
