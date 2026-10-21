# Weekend infra

O DataFood roda **local** (`docker compose` numa máquina do restaurante ou
do operador). Restaurante tem pico no fim de semana: mais buscas e mais
promoções. Em vez de pagar servidor o mês inteiro, a plataforma **sugere
contratar infraestrutura só de sexta à noite a domingo** quando a carga
prevista passa do que a máquina local aguenta.

## Como a sugestão é calculada (`promotions/infra.py`)
1. **Histórico:** média por dia da semana nas últimas 4 semanas de
   mensagens enviadas (`PromotionDelivery` `sent`) e de buscas
   (`SearchHistory` — só de quem consentiu, então é um piso da demanda real).
2. **Agendado:** promoções `scheduled` para o próximo fim de semana × o
   alcance atual de cada uma (pessoas × canais).
3. **Pico previsto** = maior dia de sex/sáb/dom: `max(histórico, agendado)`
   para mensagens; histórico para buscas.
4. **Utilização** = pico ÷ capacidade local (`LOCAL_CAPACITY_MESSAGES_PER_DAY`,
   `LOCAL_CAPACITY_SEARCHES_PER_DAY`), pegando a pior das duas.

O aviso aparece no topo do painel só para contas **admin** (é decisão de
operação da plataforma, não do restaurante).

| Utilização | `level` | Painel |
|---|---|---|
| < 70% | `ok` | linha discreta: "fim de semana tranquilo" |
| 70–99% | `attention` | aviso terracota com os motivos |
| ≥ 100% | `hire` | aviso vermelho: contratar |

Janela sugerida: **sexta 17h → domingo 23h** (54 h). Custo estimado =
54 × `WEEKEND_INFRA_HOURLY_COST` (R$/h de uma VPS de 4 GB; ajuste ao seu
provedor). O endpoint só devolve agregados — nenhum dado pessoal.

### Calibrar a capacidade
Os defaults (2000 mensagens e 3000 buscas/dia) são conservadores para um
notebook com Ollama em CPU. Meça na sua máquina: rode o smoke
(`final-tests/api_smoke.py`) e uma busca em loop e veja a latência do
shinzou; com e-mail, o limite costuma ser do provedor SMTP (ex.: contas
gratuitas limitam centenas/dia) — use o menor.

## Quando o painel sugerir: passo a passo
1. **Sexta, até 17h** — suba uma VPS (≥ 4 GB RAM) e siga
   [[deploy]] (`docker-compose.prod.yml` + Caddy/HTTPS).
2. **Dados:** a VPS precisa do banco local. Na máquina local:
   ```bash
   docker compose exec db pg_dump -U dtfd -Fc dtfd > fim-de-semana.dump
   ```
   Copie e restaure na VPS (`pg_restore -U dtfd -d dtfd --clean`), depois
   `reindex_restaurants` só se mudou o modelo de embeddings.
3. **Tráfego:** aponte o DNS (ou o link compartilhado) para a VPS. Desligue
   `worker`/`beat` locais para não haver dois disparando promoções e dois
   bots lendo o Telegram (o `getUpdates` só aceita um leitor).
4. **Segunda** — volte: `pg_dump` na VPS → `pg_restore` local, religue
   worker/beat locais, aponte o DNS de volta e **destrua a VPS** (é aí que
   a conta fica barata).

> Dica: promoções agendadas para o fim de semana entram na projeção. Agende
> cedo e o aviso chega com antecedência.
