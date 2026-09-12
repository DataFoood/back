# DataFood — Wiki do projeto

Documentação viva no padrão **LLM Wiki** (Karpathy): coleção de markdown
interligado, mantida incrementalmente, não re-derivada a cada vez.

## Como navegar
Comece pelo [[index]] — catálogo por categoria. Cada página linka as
relacionadas. O [[log]] é o registro cronológico do que mudou.

## Convenção de manutenção
- **index.md** — catálogo orientado a conteúdo. Toda página nova entra aqui.
- **log.md** — append-only. Toda mudança relevante de arquitetura/escopo vira
  uma linha datada.
- **Páginas** — uma por tema. Linkam-se entre si com **wikilinks** Obsidian
  (`[[nota]]` ou `[[nota#Seção|texto]]`). Use links markdown só pra alvos fora
  da wiki (ex.: `../API_MAP.md`) e URLs externas.
- **Fonte da verdade do contrato HTTP** é o Swagger (`/api/docs/`), gerado do
  código. A wiki explica o *porquê* e a estrutura; o Swagger dá o *o quê* exato.

## Camadas (como no padrão)
| Camada | Aqui |
|---|---|
| Raw sources | o código (`dtfd/`, `shinzou/`) — imutável, fonte |
| Wiki | esta pasta `docs/` — derivada, mantida |
| Schema | este README — define estrutura e workflow da wiki |
