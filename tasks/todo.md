# Execução da demonstração

Plano: [plan.md](plan.md). Medições recebidas: [vps-baseline.md](vps-baseline.md). Os itens só são concluídos com evidência; leitura do código não equivale a validação em execução.

## 1. Diagnóstico da VPS

- [x] Registrar RAM, CPU, disco, contêineres e imagens em repouso com as saídas fornecidas pelo usuário.
- [x] Identificar caminho do Compose, versão/modelos do Ollama e limites/reinícios/OOM de web e Ollama, conforme saídas fornecidas pelo usuário.
- [ ] Conferir configuração remota antes de mudanças persistentes e investigar os demais serviços se a prova de geração indicar necessidade.
- [ ] Registrar capacidade e modo de créditos CPU no console AWS, sem copiar segredos.

Verificação: saídas do terminal da instância e configuração operacional identificada. Dependência: nenhuma. Arquivos: nenhum obrigatório.

## 2. Configuração enxuta

- [x] Preparar experimento com teto temporário somente no Ollama e procedimento de retorno em ollama-probe.md; aplicação na VPS ainda pendente. Só reduzir serviços/processos se a medição justificar.
- [ ] Preservar dados, cache/throttles e autenticação; documentar aplicação e retorno. Ajustar o limite Ollama após medição, pois 512 MiB foi configurado para embeddings.
- [ ] Confirmar que recursos sem processamento assíncrono não anunciam envio/agendamento funcional na configuração reduzida.

Verificação: limites conferidos e baseline preservado. Se houver mudança de Compose, validar configuração e testes focados em deploy; smoke de login/refresh, catálogo e favoritos na instância. Dependência: 1. Arquivos prováveis: Compose efetivamente usado na VPS, testes focados e guia de operação; controles de campanhas se necessários em tarefa própria antes de omitir worker/beat.

## 3. Prova do modelo local

- [x] Testar um modelo pequeno com contexto curto e uma geração por vez, com a aplicação ativa: duas respostas reais, 12,49 s e 5,78 s, fornecidas pelo usuário.
- [x] Registrar memória após geração (674,7 MiB no Ollama; 443 MiB disponíveis no host), término natural das duas respostas e limitação factual observada.
- [ ] Medir memória, tempo de carregamento, tempo de resposta, reinícios e qualidade em português em perguntas representativas.
- [x] Registrar decisão inicial de seguir com um gerador pequeno e Django, com base nas duas respostas reais; ensaio representativo continua pendente.

Verificação: chamadas reais ao Ollama e observação da VPS em cinco consultas, incluindo primeira execução e execuções aquecidas. Dependência: 2. Arquivos: registro de resultados; configuração do modelo se necessário.

## 4. Catálogo inicial

- [ ] Obter resposta Overpass real da consulta municipal de Marília e executar prévia antes da importação.
- [ ] Importar o mesmo lote, conferir duplicatas/endereço/coordenadas/origem e manter dados demo identificados.
- [ ] Revisar os estabelecimentos do roteiro; não inventar fotos, horários, preços ou avaliações ausentes.

Verificação: contagens da importação e amostra no frontend; repetir o lote sem duplicar fontes. Dependência: 1; antes do ensaio de IA com catálogo real. Arquivos prováveis: docs/catalog.md; dados reais guardados fora do Git quando volumosos. Reutilizar import_osm --dry-run e --file.

## 5. Geração na API

- [x] Preparar localmente explicação opcional em answer, reaproveitando os cards e chamando Ollama diretamente do Django com httpx; padrão desabilitado.
- [x] Verificar geração/contrato em nove testes sem banco e validar OpenAPI. A saída do modelo é simulada nesses testes.
- [x] Preservar cards em falhas, retornando answer null; limitar contexto/saída e rejeitar texto vazio ou truncado, verificados localmente.
- [x] Preservar autenticação e acrescentar campo compatível; contexto do gerador restrito a dados públicos, sem dados da conta nesta entrega.
- [ ] Ensaiar API na VPS com banco e catálogo reais antes de ativar. A integração conversacional do frontend foi implementada localmente (etapa 6).

Verificação: regressões de API para sucesso, catálogo vazio, timeout e isolamento; inferência real na VPS após os testes. Dependências: 3 e catálogo de teste controlado. Arquivos prováveis: restaurants/views.py, novo serviço de geração, testes focados, settings.py e exemplo de configuração se necessário.

## 6. Resposta escrita no chat

- [x] Exibir resposta gerada, contagem e botão para abrir cards em tela cheia; persistir filtros/IDs e conversa no servidor.
- [x] Apresentar espera e indisponibilidade sem apagar a consulta ou mostrar sucesso falso.

Verificação: tipos, lint e navegação de chat com sucesso/falha; conferir histórico após recarregar. Dependência: 5. Arquivos prováveis no frontend: app/chat/page.tsx, lib/types.ts e E2E focado. Ler AGENTS.md e documentação local Next antes de editar.

## 7. Personalização e planos da demonstração

- [x] Definir a regra explícita de plano no backend: level >= 2 é premium, ativado administrativamente, sem cobrança; contrato em docs/conversation.md.
- [x] Premium recebe resumo de preferências/favoritos/sinais permitidos; gratuito usa a conversa atual. Respeitar allow_info e ajustes manuais.
- [x] Mostrar a diferença no chat com o mesmo modelo; não enviar dados identificadores desnecessários nem confiar em plano informado pelo cliente. Testes locais simulam a geração.

Verificação: teste de contas distintas, gratuito/premium e ausência de consentimento; comparar recomendações em catálogo controlado. Dependência: 6. Separar em duas entregas pequenas: política/contexto no backend e indicação do plano no frontend.

## 8. Ajustes visuais independentes

- [ ] Corrigir botão de cardápio quando existe menu_url sem pratos cadastrados.
- [ ] Oferecer edição de texto/nota usando PATCH existente, preservando uma avaliação por pessoa/local.
- [ ] Expor avatar público na avaliação e reutilizar componente Avatar existente.

Verificação: cada ajuste em entrega separada, com tipos/lint e cenário de navegação correspondente; testar atualização da nota agregada ao editar. Dependência: nenhuma funcional; prioridade após a prova de IA. Arquivos prováveis: detalhe de restaurante, serializer/tipos de review e testes focados.

## 9. Ensaio e conclusão

- [ ] Percorrer login, consulta, resposta, cards, personalização e detalhe na VPS sem OOM/reinícios.
- [ ] Preparar roteiro: problema, solução, hipótese de monetização, próximos passos e desenvolvimento técnico; distinguir funcionalidades entregues de propostas e dados reais de demo.
- [ ] Registrar métricas reais, limitações, imagens de retorno e backup; preparar catálogo antes do dia e aquecer o modelo no ensaio.

Verificação: execução completa com IA real na máquina de destino e build/testes apropriados aos arquivos alterados. Dependências: 4, 6 e 7; incluir 8 conforme tempo disponível. Arquivos prováveis: roteiro e documentação de operação.
