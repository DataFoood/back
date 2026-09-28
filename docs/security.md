# Security

Segurança é requisito não-negociável do projeto. Resumo dos controles.

## Autenticação — JWT (simplejwt, HS256)
- Login por email → `{access, refresh}`.
- Rotas protegidas exigem `Authorization: Bearer <access>`.
- **token_type:** o backend (e o shinzou) checam a claim `token_type`. Um
  **refresh** token **não** é aceito como credencial → 401. Evita escalonar um
  refresh de longa vida em acesso a recurso.

## Autorização — camadas de permissão
| Permissão | Onde | Regra |
|---|---|---|
| `AllowAny` | register, login | aberto |
| `IsAuthenticated` | consent, change-password, favoritos, busca, preferences | logado |
| `IsOwnerOrAdmin` | user detail/delete | dono ou staff |
| `IsRestaurantOwnerOrAdmin` | restaurant update/delete | dono do restaurante |
| `IsAuthorOrAdmin` | reviews | autor da review |
| `IsParentRestaurantOwnerOrAdmin` | items/images/hours | dono do restaurante pai |
| `IsEntityOwnerOrAdmin` | addresses | dono da entidade alvo |
| `IsAdminUser` | listas de users, recompute, reindex | só `is_staff` |

## Rate limiting (anti brute-force)
`ScopedRateThrottle` nas rotas sensíveis: **login 5/min**, **register 10/h** por
IP, **busca 30/min** por usuário. Contador no Redis (compartilhado entre
workers).

**Identidade do cliente = IP, e o IP depende de `NUM_PROXIES`.** Sem essa
configuração o DRF usa o `X-Forwarded-For` inteiro como identidade — header
que o próprio cliente envia. Foi assim até 2026-09-28: trocando o XFF a cada
tentativa o limite de login nunca disparava (brute force livre). Agora:

| Ambiente | `NUM_PROXIES` | Identidade |
|---|---|---|
| dev / acesso direto | `0` (default) | `REMOTE_ADDR` |
| produção atrás do Caddy | `1` (já no `docker-compose.prod.yml`) | último salto do XFF, preenchido pelo Caddy |

Proxy próprio com mais saltos → ajuste para o número de proxies confiáveis.
Errar para menos reabre o bypass; errar para mais faz todo mundo dividir o
mesmo contador.

## Sessão (JWT)
Access de 15 min, refresh de 7 dias com **rotação** (cada refresh gera outro e
o antigo vai pra blacklist). `POST /api/users/logout/` invalida o refresh.

**Revogação em massa** (`users.serializers.revoke_refresh_tokens`): blacklista
todos os refresh emitidos para o usuário.
- **Troca de senha** revoga tudo e responde com um par novo
  (`{detail, access, refresh}`) para a sessão atual seguir — quem roubou um
  refresh perde o acesso na hora.
- **Encerrar conta** (soft delete) revoga tudo.
- Access tokens já emitidos continuam válidos até expirar (≤ 15 min) — é o
  custo do JWT stateless; o soft delete também põe `is_active=False`, que o
  `JWTAuthentication` recusa na hora.

**Refresh de conta removida → 401.** O serializer do simplejwt faz
`User.objects.get()`; como o manager filtra soft-deleted, estourava
`DoesNotExist` (500). `RefreshSerializer` converte em 401
`no_active_account`.

## CORS / CSRF
Dev (`DEBUG=True`, env vazio): `localhost`/`127.0.0.1` nas portas 3000-3002 e
5000-5002. Produção: `CORS_ALLOWED_ORIGINS` e `CSRF_TRUSTED_ORIGINS` por env.

## Soft delete e bloqueio de login
DELETE de usuário seta `deleted_at` **e** `is_active=False` → login barrado na
hora. Registros soft-deleted somem das listagens padrão (`ActiveManager`). Ver
[[data-model]].

## Ponte Django ↔ shinzou (B2B interno)
Duas camadas: `X-Service-Token` (constant-time, `hmac.compare_digest`) +
Bearer JWT do usuário validado com a `SECRET_KEY` compartilhada. O shinzou
**não é exposto** publicamente — só o Django o alcança. Ver
[[search-rag]].

## LGPD — consentimento (`allow_info`)
- Campo booleano no usuário, **default false**.
- SearchHistory, `RestaurantView` por usuário e o recompute de afinidades só
  acontecem com `allow_info=true`. O dono vê apenas `view_count` (contador
  anônimo) e agregados.
- Perfil de terceiros (`GET /users/<id>/`) só expõe nome/avatar/banner.
- Reviews públicas mostram só o primeiro nome do autor.
- Sem consentimento: a busca funciona, mas nada é persistido sobre ela.
- Toggle: `PATCH /api/users/consent/` `{allow_info: bool}` (só o próprio user).

## Validação de entrada
- Payload inválido é **400**, nunca 500/503. Busca: `query` texto de até 500
  caracteres (vira embedding — custo), `limit` inteiro 1..50. Recompute:
  `user_id` inteiro.
- URLs guardadas (`cover_image`, `website`, `menu_url`, fotos) passam pelo
  `URLValidator` do Django → `javascript:` é rejeitado (o front as usa em
  `href`/`src`).
- Métrica do dono: `view_count` ignora acessos do próprio dono/admin (o
  painel recarrega o detalhe a cada edição e inflava o número).

## Testes de segurança
- `final-tests/test_security_regressions.py` — regressões dos achados de
  2026-09-28 + varredura de autorização (intruso tentando escrever em
  restaurante, itens, fotos, horários, endereço e conta de outro).
- `final-tests/api_smoke.py` — contra o stack rodando: CORS, rotação/blacklist
  de refresh, revogação na troca de senha, isolamento entre contas.

## Endurecimento de produção
`DEBUG` é **False por padrão**. Sem `DEBUG=True`, a aplicação se recusa a
subir sem `SECRET_KEY` e `SHINZOU_SERVICE_TOKEN`. Bloco `if not DEBUG` no
`settings.py`: HTTPS redirect (exceto `/api/health/`), cookies seguros, HSTS,
`SECURE_PROXY_SSL_HEADER`. `manage.py check --deploy` passa sem avisos.
