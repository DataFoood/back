# Medição inicial da VPS

Fonte: saídas fornecidas pelo usuário em 19/11/2026, coletadas no terminal da EC2. Não foram executadas por esta sessão. Instância informada: t3.small, us-east-2.

## Host

| Indicador | Valor informado |
| --- | --- |
| RAM total | 1,9 GiB |
| RAM usada | 916 MiB |
| RAM disponível | 988 MiB |
| RAM livre | 275 MiB |
| Buffers/cache | 923 MiB |
| Swap usada / total | 216 MiB / 4 GiB |
| Load 1/5/15 min | 0,06 / 0,09 / 0,10 |
| Disco raiz | 19 GiB usados, 9,1 GiB disponíveis, 68% |
| Uptime | 1 dia e 14 horas |

O valor disponível já considera memória recuperável; não somar novamente buffers/cache. Swap ocupada sozinha não comprova pressão atual: nas quatro amostras por intervalo do vmstat, si=0 e so=0. A primeira linha é uma média desde o boot. CPU ociosa entre 80% e 100% nas amostras por intervalo; não há evidência de saturação sustentada neste retrato.

## Contêineres

| Nome | Memória informada |
| --- | ---: |
| backend-web-1 | 142,3 MiB |
| backend-caddy-1 | 34,95 MiB |
| backend-worker-1 | 75,71 MiB |
| backend-shinzou-1 | 39,04 MiB |
| backend-db-1 | 36,25 MiB |
| backend-beat-1 | 47,82 MiB |
| backend-redis-1 | 7,836 MiB |
| backend-ollama-1 | 24 MiB |

Soma aproximada: 407,9 MiB. Worker + beat: 123,53 MiB. A soma do docker stats não substitui a medição global do host, nem inclui necessariamente o mesmo tratamento de cache/swap.

Todos exibiram limite de 1,86 GiB. A inspeção posterior confirmou HostConfig.Memory=0 e MemorySwap=0 para web e Ollama: sem limite individual configurado. Ambos tinham RestartCount=0 e State.OOMKilled=false. Isso não exclui eventos do kernel ou mortes anteriores de subprocessos. Os demais contêineres estavam Up 38 hours; não foi inspecionada a contagem deles.

Compose efetivo informado: /home/ubuntu/backend/docker-compose.prod.yml. Imagens backend-* locais, pgvector:pg16, Redis 7, Caddy 2 e Ollama latest. Binário Ollama confirmado: 0.34.4. Modelos: nomic-embed-text:latest instalado (274 MB); ollama ps vazio antes do teste. Download de qwen3:0.6b concluído com sucesso.

Não apareceu contêiner do frontend. Não inferir onde ele está hospedado nem recriar a stack pelo Compose local antes de identificar os arquivos usados na EC2.

## Decisão após a medição

Não reescrever Django ou remover serviços com base neste consumo em repouso. O próximo experimento é geração local com modelo pequeno e limites controlados, com a aplicação ativa; só depois considerar cortes comprovadamente necessários. Ollama a 24 MiB não representa memória durante inferência.

## Prova inicial recebida: geração real

O usuário executou o bloco de duas chamadas com limite de 900 MiB de RAM e 1200 MiB de RAM+swap, contexto 1024, 120 tokens de saída, uma thread e thinking desabilitado. Aplicação e serviços anteriores permaneceram ativos. O script final descarregou o modelo e removeu o limite experimental; não existe alteração persistida no Compose.

| Indicador | Primeira chamada | Segunda chamada |
| --- | ---: | ---: |
| Tempo total informado pelo Ollama | 12,49 s | 5,78 s |
| Carregamento | 4,70 s | 0,01 s |
| Tokens gerados | 83 | 76 |
| Motivo de término | stop | stop |

Após as consultas, ollama ps mostrou qwen3:0.6b residente, 663 MB, CPU, contexto 1024. Docker stats: Ollama 674,7 MiB de 900 MiB; web 101,1 MiB; host com 443 MiB disponíveis. Web/Ollama continuaram com zero reinícios registrados e OOMKilled=false. Esses campos não comprovam ausência de OOM de subprocessos, mas as duas gerações terminaram com sucesso.

Swap passou de 248 MiB na coleta anterior para 354 MiB nesta coleta. As amostras posteriores tiveram so=0 e pequenos si; não houve medição simultânea que permita afirmar ausência de paginação durante a geração. O pico de RAM e a CPU durante as chamadas não foram capturados.

As duas respostas escolheram a opção vegetariana de R$ 30 para um teto de R$ 35. A primeira chamou incorretamente R$ 30 de valor máximo permitido; a segunda mencionou o saldo de R$ 5. Isso comprova geração em português e viabilidade inicial, sem comprovar qualidade geral ou precisão factual. Usar fatos do catálogo e resposta curta; não tratar o prompt como garantia de correção.

Decisão: avançar com um gerador e Django, preservando os serviços; não há evidência para reescrita por memória. A próxima validação é com restaurantes recuperados pela aplicação, contexto maior e perguntas variadas. A explicação opcional na API foi preparada localmente, desabilitada por padrão; ainda não foi publicada ou ensaiada na VPS.

Pendentes: conteúdo/configuração efetiva do Compose remoto, créditos CPU AWS, limites persistentes, pico durante carga e ensaio com catálogo real. Esta sessão não tem conexão direta com a VPS.

## Verificação local da primeira integração

- Nove testes novos Django sem banco passaram, com Ollama simulado: autenticação/entrada, geração, formato/término, contexto público limitado, falha e preservação dos cards.
- OpenAPI validado sem avisos pelo comando spectacular --validate --fail-on-warn.
- Verificação adicional: oito testes de embeddings/ranking/Compose small passaram. Os três testes existentes de inicialização POSIX não executaram corretamente no Windows: inicialmente faltou sh; com Git sh, os stubs e caminhos POSIX não produziram o log esperado. Não foram alterados ou desabilitados. Validação desses testes continua pendente em Linux/CI.
- Revisão incluiu inverter temporariamente a condição da flag: três testes falharam, detectando a mutação. Arquivo original restaurado byte a byte.
- Dependências existentes instaladas com uv sync --frozen, sem alterar manifesto ou lockfile. Docker local não está ativo e não há PostgreSQL/Redis locais disponíveis para a suíte Django completa.
- Nenhuma publicação, migração ou alteração persistente na VPS. Frontend e personalização por plano permanecem pendentes.
