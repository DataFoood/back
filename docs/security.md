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
IP. Contador no Redis (compartilhado entre workers).

## Sessão (JWT)
Access de 15 min, refresh de 7 dias com **rotação** (cada refresh gera outro e
o antigo vai pra blacklist). `POST /api/users/logout/` invalida o refresh.

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

## Endurecimento de produção
`DEBUG` é **False por padrão**. Sem `DEBUG=True`, a aplicação se recusa a
subir sem `SECRET_KEY` e `SHINZOU_SERVICE_TOKEN`. Bloco `if not DEBUG` no
`settings.py`: HTTPS redirect (exceto `/api/health/`), cookies seguros, HSTS,
`SECURE_PROXY_SSL_HEADER`. `manage.py check --deploy` passa sem avisos.
