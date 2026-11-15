# Implementação — situação e operação

Data: 04/11/2026. Escolha aprovada: Marília/SP + OpenStreetMap. O plano inicial
está em [implementation-plan.md](implementation-plan.md); a execução ocorreu
por commits incrementais diretamente em main, conforme solicitado.

## Código entregue

- Validade de campanhas verificada no agendamento, na edição e no worker.
- Reserva transacional de cota por usuário, compartilhada entre campanhas/canais.
- Outbox persistente, recuperação do broker, posse de processamento renovável,
  tentativas limitadas e separação de aceitação, falha e resultado desconhecido.
- Importador OSM idempotente para Marília, procedência/atribuição, histórico da
  importação e revisão administrativa; edições do dono não são sobrescritas.
- Identificação conservadora de seeds legados e isolamento de demos em produção.
- Cidade/proximidade antes da paginação e do ranking; recuperação textual quando
  o motor semântico falha; afinidade não apresentada como probabilidade.
- Telefone separado de WhatsApp confirmado pelo dono/admin.
- Eventos de interesse, atribuição assinada por campanha/canal, confirmação de
  resgates pelo restaurante e deduplicação de referência.
- Painel com 7/30/90 dias, comparação de janelas, indicação de amostra insuficiente,
  gráficos/tabela, campanhas, resgates e exportação CSV.
- Retenção e reconstrução idempotente de agregados; eventos sem vínculo com conta
  do visitante; medição do navegador respeita DNT e flag de desativação.
- Telemetria operacional agregada, p95 por faixas, snapshots opcionais de recursos
  do contêiner da API e indicação de capacidade ainda não calibrada.
- Benchmark de busca e script de backup com restauração em banco temporário.
- Capitalização incorporada da branch revisada; apresentação comercial ajustada
  para não anunciar preços, API de demanda e BI regional não implementados.

## Instalação e atualização

Os manifestos e lockfiles de dependências não mudaram (exceto scripts do pacote
isolado de E2E). Após atualizar código, execute as migrações antes de iniciar o
fluxo normal, reinicie API, shinzou, worker e beat e gere o build do front.

```bash
cd dtfd
uv run python manage.py migrate --noinput
# Após liberar rede e obter uma consulta real bem-sucedida:
uv run python manage.py import_osm --dry-run
uv run python manage.py import_osm
uv run python manage.py reindex_restaurants
```

Consulte [catalog.md](catalog.md), [promotions.md](promotions.md),
[analytics.md](analytics.md) e [weekend-infra.md](weekend-infra.md).
Mantenha `SHOW_DEMO_RESTAURANTS=False` em produção. Não executar seed de contas
demo em produção. Configure endereço público HTTPS, origens e canais reais antes
de compartilhar links com clientes.

## Evidências locais

- Suíte Django completa: 281 testes passaram.
- Regressões de segurança adicionais: 16 testes passaram.
- Ranking shinzou: 6 testes passaram.
- OpenAPI validado sem avisos; migrações consistentes.
- Tipos, lint e build do front passaram.
- Navegação E2E geral: 49 verificações passaram.
- Promoções E2E: 16 verificações passaram (e-mail no console, sem Telegram real).
- BI E2E: 12 verificações passaram, incluindo atribuição, resgate, CSV e celular.
- pgvector real respeitou conjunto de candidatos vazio e ID permitido.
- Dump local restaurado com sucesso em banco temporário, preservando o ativo.
- Benchmark executou três buscas; usou o simulador local, portanto não calibra
  capacidade de produção nem comprova relevância de um modelo real.

## Atualização de prontidão — 15/11/2026

- Dependências atualizadas pelo lockfile, incluindo Django 6.1.3, DRF 3.18.3,
  PyJWT 2.15.1, FastAPI 0.163.1, Gunicorn 27.0.1 e Celery 5.7.0.
  Django e PyJWT agora são dependências diretas. Auditoria com `pip-audit`
  não encontrou vulnerabilidades conhecidas no ambiente atualizado.
- Comando de produção corrigido: todas as opções chegam ao Gunicorn e `exec`
  permite que o servidor receba os sinais de parada do contêiner. A versão do
  uv está fixada em 0.12.0 no Docker e no CI.
- A classe de testes de envio de promoções habilita tarefas síncronas por
  conta própria. Suíte completa: 284 testes Django, 16 regressões de segurança,
  6 testes de ranking e 3 regressões de inicialização passaram. Sem depender
  de `CELERY_TASK_ALWAYS_EAGER=True` no ambiente da suíte.
- Migrações consistentes e aplicadas em banco vazio com pgvector; OpenAPI e
  checks Django de produção passaram. Imagem Docker construída, validada em
  modo produção e com `collectstatic` executado como usuário sem root.
- Integração na imagem atualizada: 83/83 checagens HTTP passaram com Postgres,
  Redis, shinzou e Ollama simulado. O log confirmou três workers do Gunicorn.
  Esse ensaio usa dados demo isolados e não comprova qualidade semântica real.
- CI adicionado para PRs e main: auditoria, testes, migrações, schema, checks
  de produção, build e validação de estáticos dentro da imagem.

As pendências externas abaixo continuam necessárias antes de liberar o piloto
público. Não houve deploy remoto nem envio para canais reais nesta atualização.

## Pendências que impedem declarar o piloto real concluído

1. **Dados reais:** o proxy deste ambiente negou HTTPS para `overpass-api.de`.
   Os domínios `overpass-api.de` e `www.openstreetmap.org` foram salvos no
   rascunho das configurações do ambiente, mas a política em execução ainda
   não os recebeu. É necessário revisar/salvar as configurações e publicar o
   ambiente de desenvolvimento; depois executar e conferir a importação real.
   Nenhum fixture foi apresentado como catálogo verdadeiro.
2. **Qualidade de busca:** validar cobertura local, duplicatas, atualizações,
   filtros e relevância com dados reais e modelo de embeddings real. O teste
   de integração com simulador não satisfaz esse critério.
3. **Canais reais:** Telegram/SMTP não foram validados com contas controladas.
   Configurar credenciais com segurança e definir destinatários de teste antes
   de realizar envios reais. WhatsApp permanece compartilhamento manual.
4. **Operação pública:** endereço acessível ao público, configuração HTTPS,
   provedor/orçamento, capacidade medida e ensaio de corte/retorno ainda dependem
   da instalação de destino. Não houve contratação nem deploy remoto nesta tarefa.

BI não estima vendas por cliques, receita desconhecida ou insights de bairro sem
amostra. Resgates são declarações auditáveis do restaurante, sem validação fiscal
externa. A revisão administrativa não automatiza verificação de titularidade.
Migração sem pausa e provisionamento automático de nuvem são etapas posteriores.
