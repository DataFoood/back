# Promotions

Promoções por mensageiros: o dono escreve uma vez no painel e ela chega por
**Telegram** e **e-mail** a quem salvou o restaurante, e vira um link pronto
de **WhatsApp** para o dono disparar na própria lista de transmissão. App
`dtfd/promotions/`. Rotas em [../API_MAP.md](../API_MAP.md) (seção
Promotions).

## Quem recebe
Só quem **favoritou o restaurante E deu opt-in** (`MessagingPreference.
promotions_opt_in`) — consentimento próprio, separado do `allow_info`
(LGPD: finalidade diferente). `opted_in_at` guarda quando ligou. Por canal:

| Canal | Condição | Como chega |
|---|---|---|
| Telegram | `channel_telegram` + conta vinculada ao bot + `TELEGRAM_BOT_TOKEN` | Bot API (`sendMessage`) |
| E-mail | `channel_email` | backend do Django (console em dev, SMTP via env) |
| WhatsApp | — (manual) | `wa.me/?text=…` com o texto pronto; o dono escolhe lista/grupo/status. Nenhum telefone de cliente sai da plataforma |

Descadastro: link assinado no fim de cada e-mail (+ header
`List-Unsubscribe`) → `/promocoes/descadastrar` no front → `POST
/api/promotions/unsubscribe/`; `/sair` no bot; toggle no perfil.

## Ciclo de vida
```
draft ──send/ {}──────────────▶ sending ──worker──▶ sent
  │  ▲                              ▲
  │  └─unschedule/─┐                │ beat (todo minuto)
  └─send/ {scheduled_for}─▶ scheduled
```
- Criar = sempre rascunho. Editar só em `draft`/`scheduled`.
- `DELETE` = soft delete: tira da vitrine; mensagens enviadas não voltam.
- Sem canal marcado, "enviar" só **publica** (página do restaurante + link
  do WhatsApp).

## Garantias do envio (`services.deliver`)
- **Idempotente:** `PromotionDelivery` é único por (promoção, usuário,
  canal). Cada entrega é *reservada* (`pending → sending`, update
  condicional) antes de sair — dois workers nunca mandam a mesma; se o
  worker morre no meio, a entrega fica `sending` e **não** é reenviada
  (melhor perder uma do que mandar em dobro).
- **Retomada:** promoção em `sending` há mais de 15 min (máquina local
  desligou) é retomada pelo beat; só as entregas ainda `pending` saem.
- **Falha isolada:** erro num destinatário vira `failed` com o motivo e o
  lote segue. Bot bloqueado (403) desvincula o Telegram da conta. 429 do
  Telegram: espera o `retry_after` (até 30 s) e tenta uma vez.
- **Anti-spam:** `PROMOTIONS_MAX_PER_DAY` por restaurante (enviadas +
  agendadas no dia, inclusive removidas — remover não devolve a cota;
  restaurante travado com `select_for_update`) e
  `PROMOTIONS_USER_DAILY_CAP` promoções por pessoa em 24 h, somando todos
  os restaurantes (excedente vira `skipped`).

## Telegram local (sem URL pública)
Vínculo por **long polling**: `poll_telegram` (beat, a cada
`TELEGRAM_POLL_SECONDS`) chama `getUpdates`, processa `/start <token>` e
`/sair`, e guarda o offset no cache. Lock no cache evita duas execuções
sobrepostas. Só conversa **privada** vincula (grupo receberia promoções de
uma pessoa). Token de vínculo: aleatório, uso único, 15 min. Um chat = uma
conta (vincular em outra desvincula a anterior).

Configurar: crie o bot no @BotFather → `TELEGRAM_BOT_TOKEN` e
`TELEGRAM_BOT_USERNAME` no `.env` → `docker compose up -d --force-recreate
web worker beat`. Sem token o canal some do painel e o resto funciona.

## Sugestão de infra no fim de semana
`GET /api/promotions/infra-suggestion/` — **só admin** (números agregados da
plataforma inteira; dono de restaurante não vê). Ver
[[weekend-infra]].

## Modelos
| Modelo | Campos-chave |
|---|---|
| `MessagingPreference` | user (1:1), promotions_opt_in, opted_in_at, channel_email, channel_telegram, telegram_chat_id, telegram_link_token/expires_at |
| `Promotion` (AbstractAudit) | restaurant, created_by, title, message, coupon_code, valid_until, send_telegram, send_email, status, scheduled_for, dispatched_at, sent_at |
| `PromotionDelivery` | promotion, user, channel, status (pending/sending/sent/failed/skipped), error, sent_at |
