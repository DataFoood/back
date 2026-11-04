# Medição e BI

`POST /api/insights/events/` recebe um UUID de deduplicação, restaurante e um
tipo enumerado: impressão visível, abertura de detalhe, clique em contato,
cardápio ou rota. Não aceita compra, resgate, valor, usuário, consulta livre,
IP ou timestamp do cliente. Impressão só é emitida quando o card fica visível;
visitas do dono/admin são ignoradas. São contagens observadas, não pessoas
únicas; bloqueadores e DNT podem reduzir a amostra. Eventos do navegador são
sinais de interesse e podem conter ruído/abuso; nunca comprovam receita.

Campanhas geram referência assinada por campanha/canal, sem identificação do
destinatário. A referência só atribui eventos ao mesmo restaurante. Não se
usa cookie de rastreamento ou identificador persistente de sessão para o BI.
O mecanismo padrão de sessão da aplicação continua separado desta medição.
`NEXT_PUBLIC_ANALYTICS_ENABLED=false` desliga a coleta no front; DNT é respeitado.
A política de privacidade deve explicar essa medição, e o operador deve
verificar a base legal aplicável ao uso concreto antes do lançamento público.

`GET /api/restaurants/<id>/analytics/?days=7|30|90` é exclusivo do dono/admin.
Os intervalos atual e anterior têm a mesma duração, terminando no horário da
requisição. Séries diárias têm primeiro/último dia parcial. Sem eventos que
antecedam a janela comparada, o relatório indica histórico insuficiente.
Amostra ausente não produz crescimento fictício. `&export=csv` exporta datas e
contagens (sem texto de origem externa/células executáveis).

`POST /api/restaurants/<id>/redemptions/` exige dono/admin, promoção publicada
com cupom válido, referência interna sem dados pessoais e valor opcional.
A referência é única por restaurante. Repetir a mesma referência/payload não
duplica o resgate; alterar valor/promoção responde 409. É confirmação declarada
pelo restaurante, não verificação fiscal externa. Valores não informados
continuam desconhecidos; não se estima receita nem ROI a partir de cliques.

`python manage.py refresh_insights` reconstrói agregados diários de forma
idempotente e aplica retenção de 180 dias a eventos e entregas finalizadas.
180 dias permitem comparar 90 com os 90 anteriores. O beat executa diariamente.
Os eventos não têm vínculo com a conta do visitante. Referências de resgate
são internas e o responsável pela confirmação é conservado para auditoria.

Antes de instalar a versão: `python manage.py migrate`. Sem eventos reais,
o painel permanece vazio, sem indicadores inventados. O serviço usa índices
por restaurante/data e agregações independentes, sem consulta por campanha.
