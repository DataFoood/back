# Plano: demonstração DataFood com IA local

Preparado em 19/11/2026. Estado: repouso e duas gerações reais na VPS medidos;
chat conversacional e seleção em tela cheia implementados localmente, com geração
desabilitada por padrão. Contexto premium autorizado e testes de isolamento
incluídos. Ensaio integrado na VPS e catálogo real ainda pendentes.
Evidências: [vps-baseline.md](vps-baseline.md); contrato: [conversation.md](../docs/conversation.md).

## Objetivo e prazo

Demonstrar descoberta de restaurantes reais e resposta escrita com contexto autorizado do usuário, com um usuário por vez e inferência inteiramente local. Trabalhar para 01/12/2026; 08/12 é a segunda data informada. A instância informada é AWS t3.small, us-east-2: 2 GiB de RAM e 2 vCPUs. O acesso disponível ao usuário é o console AWS; esta sessão não tem conexão com a instância.

## Decisões propostas

- Preservar Django/DRF, Next.js, PostgreSQL, dados e autenticação existentes. A medição inicial não mostrou saturação em repouso; ajustar recursos e só reduzir processos quando a medição justificar, antes de avaliar reescrita.
- Testar um único gerador pequeno, começando por Qwen3 0.6B quantizado, contexto curto e uma geração por vez. O tamanho do arquivo não comprova RAM de execução nem qualidade em português.
- Usar o mesmo modelo nos planos gratuito e premium. O backend decide o plano; premium acrescenta preferências e sinais autorizados, sem treinamento do modelo ou cobrança nesta etapa.
- Recuperar restaurantes por texto/filtros existentes e gerar explicação fundamentada nos registros retornados. Não depender de embeddings/shinzou nesta experiência inicial.
- Manter Redis enquanto atender cache/throttles. Worker/beat só saem da configuração de demonstração após tratar as funções que dependem deles; não deixar campanhas aparentando envio sem consumidor.
- Reaproveitar importador OSM de Marília/SP e guardar resposta real antes da apresentação. Preservar origem e distinguir dados reais de demonstração.
- Não sobrescrever o plano histórico em docs/implementation-plan.md. Este plano trata apenas do recorte da apresentação.

## Execução e dependências

Checklist e critérios detalhados: [todo.md](todo.md).

1. Medir instalação atual e identificar Compose/processos em uso.
2. Preparar limites controlados para a prova de geração; qualquer redução de processos depende de evidência, com retorno à instalação anterior e verificação de recursos afetados.
3. Provar geração local com o restante da aplicação ativo; comparar primeira execução e execuções aquecidas.
4. Importar/revisar catálogo real usando o importador existente.
5. Integrar geração à API, preservando cards e fallback quando o modelo falhar.
6. Exibir e persistir a resposta escrita no chat.
7. Aplicar contexto premium autorizado e demonstrar diferença de planos em contas controladas.
8. Corrigir acesso ao cardápio, acrescentar edição da avaliação e avatar, em mudanças separadas.
9. Ensaiar o percurso do pitch e registrar as métricas reais da máquina.

A prova de capacidade vem antes da integração. Se o modelo não atender no hardware atual, registrar o resultado e discutir a menor mudança de infraestrutura; não mascarar uma resposta pronta como geração ao vivo.

## Fora do recorte

Migração de framework/banco, dois geradores residentes, pagamento de assinaturas, upload e análise documental, novas exigências de CPF/gênero/nascimento e novas regras de múltiplas avaliações. Funcionalidades existentes não são excluídas do código por estarem fora da apresentação.

## Verificação e riscos

- Medir RAM disponível, memória por contêiner, CPU, reinícios/OOM e latência durante geração. Tetos do Compose não são consumo medido.
- Testar primeiro chamadas isoladas ao modelo, depois o fluxo real com autenticação, banco e frontend ativos. Definir meta de latência com base no ensaio e no tempo disponível para o pitch.
- Testes da API devem cobrir falha/timeout, resposta sem restaurantes e isolamento/consentimento do contexto. Testes com simulador não comprovam desempenho do modelo real.
- Não confiar no plano ou em mensagens privilegiadas enviados pelo navegador. Não fornecer CPF, telefone, e-mail ou todo o histórico ao modelo sem necessidade.
- Validar login/refresh, catálogo, favoritos e chat após mudanças de infraestrutura. Medir também créditos CPU da T3 no console AWS.
- Antes de mudanças persistentes na VPS, conferir backup e comando de retorno. Não apagar volumes nem executar build pesado na instância pequena.

## Pendências

Compose e versão/configuração Ollama efetivamente usados; reinícios/OOM e créditos CPU; qualidade e latência do gerador; cobertura atual do catálogo OSM; definição de quais funções de campanhas entram no roteiro. A medição de repouso já foi recebida; ela não valida capacidade durante inferência.
