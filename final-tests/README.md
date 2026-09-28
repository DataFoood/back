# final-tests (back)

Rodada final de testes de integração e segurança (2026-09-28). Tudo que foi
criado ou descoberto nela fica aqui.

| Arquivo | O quê |
|---|---|
| `test_security_regressions.py` | 16 testes Django: um por achado + varredura de autorização. **Falham no código anterior, passam no atual.** |
| `api_smoke.py` | 67 checagens contra a API **rodando** (sem mocks): visitante, cliente, dono, sessão, CORS, limpeza |
| `fake_ollama.py` | Ollama falso (`POST /api/embeddings`) para rodar a busca semântica sem GPU/modelo |

## Como rodar

Com Docker (o jeito normal do projeto):

```bash
docker compose up -d --build
docker compose exec -w /app/dtfd web uv run python manage.py seed_demo --demo-users
docker compose exec -w /app/dtfd web uv run python manage.py reindex_restaurants

# regressões (dentro do container, a pasta precisa estar montada — ou rode local)
docker compose exec -w /app/dtfd web uv run python manage.py test ../final-tests
# smoke contra a API exposta em :8000
uv run python final-tests/api_smoke.py
```

Sem Docker (como esta rodada foi feita): ver "Rodar sem Docker" em
[`docs/infrastructure.md`](../docs/infrastructure.md). Em resumo: Postgres 16 +
`postgresql-16-pgvector`, Redis, `fake_ollama.py`, shinzou e `runserver`.

```bash
cd dtfd
uv run python manage.py test               # 178 testes da suíte
uv run python manage.py test ../final-tests  # 16 regressões
cd .. && uv run pytest shinzou/tests        # 6 do shinzou
uv run python final-tests/api_smoke.py      # 67 checagens (API em :8000)
```

Observações:
- O smoke faz 2 logins; o limite é 5/min por IP. Para repetir em sequência:
  `redis-cli -n 1 flushdb` (zera os contadores do throttle em dev).
- Busca: com shinzou + Ollama (real ou falso) o smoke valida resultados; sem
  eles aceita 503 e avisa.
- Com o `fake_ollama.py` o `% match` é baixo (0–10%): o vetor é
  bag-of-words, não semântico. Serve para testar o pipeline, não a
  relevância.

## Resultado

| Suíte | Resultado |
|---|---|
| Django (`manage.py test`) | 178/178 |
| Regressões (`final-tests`) | 16/16 (14 falhas/erros no código anterior) |
| shinzou (`pytest`) | 6/6 |
| Smoke (`api_smoke.py`) | 67/67 |
| Schema OpenAPI (`spectacular --validate --fail-on-warn`) | ok |
| Navegação E2E do front (`front-end/final-tests`) | 48/48 |

## Achados e correções

Cada item foi reproduzido contra a API rodando antes de corrigir.

| # | Severidade | Problema | Correção |
|---|---|---|---|
| 1 | **alta** | Rate limit de login burlável: trocando o `X-Forwarded-For` a cada tentativa, nunca dava 429 (8 tentativas seguidas = 8× 401). O DRF sem `NUM_PROXIES` usa o XFF inteiro como identidade. | `NUM_PROXIES` por env: 0 em dev (usa `REMOTE_ADDR`), 1 no compose de produção (Caddy). |
| 2 | **alta** | Trocar a senha não derrubava sessões: um refresh roubado seguia renovando access por até 7 dias. | Troca de senha e encerrar conta blacklistam todos os refresh do usuário; a troca devolve par novo. |
| 3 | média | Refresh de conta removida → **500** (`User.DoesNotExist`: o manager filtra soft-deleted). | `RefreshSerializer` → 401 `no_active_account`. |
| 4 | média | `POST /api/search/` com `query` lista → **500**; `limit` texto → **503** (o erro de validação do shinzou virava "indisponível"); query de 20 mil caracteres aceita (vira embedding). | `query` texto ≤ 500, `limit` inteiro 1..50, senão 400. |
| 5 | média | Recriar o horário de um dia removido → **500** (UniqueConstraint inclui a linha soft-deleted). | Reaproveita a linha removida. |
| 6 | baixa | Dono abrindo o próprio restaurante (e o painel, que recarrega o detalhe a cada edição) inflava `view_count`. | Não conta acessos do dono/admin. |
| 7 | baixa | `POST /api/preferences/recompute/` com `user_id` não numérico → **500**. | 400. |

Conferido e **ok** (sem mudança): isolamento entre contas em todas as rotas de
escrita (restaurante, itens, fotos, horários, endereços, conta), refresh não
serve como access, rotação + blacklist do refresh, CORS só para origens
configuradas, `javascript:` rejeitado em URLs, promoção customer→owner, limite
de 6 pratos, LGPD (histórico só com consentimento, autor de review só com
primeiro nome), soft delete bloqueando login e sumindo das listagens.

Ficou para o backlog ([`docs/backlog.md`](../docs/backlog.md)): `view_count`
anônimo inflável, access token válido até 15 min após revogação, nested
GET de restaurante removido, 20 erros de pyright pré-existentes.

## Mudança de contrato

`POST /api/users/<id>/change-password/` agora responde
`{detail, access, refresh}`. O front já guarda o par novo; outros clientes
precisam fazer o mesmo, senão a sessão atual cai no próximo refresh.
