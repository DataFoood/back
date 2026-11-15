# Ubuntu / EC2 t3.small — 2 GiB

Configuração para piloto com pouco tráfego, preservando a busca semântica local.
Use `docker-compose.small.yml` sozinho, sem combinar com o Compose geral.
Ela usa imagens prontas e limites de memória; não compila o frontend na EC2.
Não houve benchmark na instância AWS de destino: medir antes de divulgar.

## Processos e memória

| Serviço | Limite |
| --- | ---: |
| PostgreSQL (30 conexões, shared_buffers 64 MB) | 256 MiB |
| Redis (32 MB para dados, sem eviction do broker) | 96 MiB |
| Django / Gunicorn (1 worker, 2 threads) | 192 MiB |
| Celery (pool solo, uma tarefa por vez) | 160 MiB |
| Celery beat | 128 MiB |
| Frontend standalone (heap Node até 128 MB) | 256 MiB |
| Caddy | 64 MiB |
| shinzou (1 worker, pool de 2 conexões) | 128 MiB |
| Ollama (1 modelo, 1 inferência por vez) | 512 MiB |

Total dos limites dos serviços persistentes: **1792 MiB**. A importação inicial
do modelo tem um cliente temporário de até 64 MiB. Esses limites não reservam
memória e não comprovam capacidade: um serviço pode atingir seu limite e ser
reiniciado. Monitore memória, reinícios, latência e espaço EBS. O kernel, Docker,
SSH e outros agentes da máquina também precisam de memória.

O modelo inicial continua sendo `nomic-embed-text` (768 dimensões). O contexto
é limitado a 512 tokens, o batch a 32 e a CPU do modelo a uma thread. O cliente
usa `/api/embed` com truncamento de textos longos e `keep_alive=0`, para
descarregar o modelo após a requisição. Isso aumenta a latência de consultas
isoladas e pode mudar os resultados para descrições longas. Reindexe o catálogo
ao alterar contexto ou modelo, e confira a relevância em português.

Modelos que retornam 384 dimensões exigem migração e reconstrução dos vetores:
alterar só `EMBEDDING_DIM` não altera a coluna existente no PostgreSQL. Mesmo
com a mesma dimensão, vetores de modelos diferentes não devem ser misturados.

## 1. Gere as imagens fora da EC2

Na sua máquina ou num runner de CI com Docker Buildx, com os dois repositórios
atualizados lado a lado. Substitua o domínio **antes** do build do frontend:

```bash
docker buildx build --platform linux/amd64 --load -t datafood-back:small-v1 ./back
docker buildx build --platform linux/amd64 --load \
  --build-arg NEXT_PUBLIC_API_URL=https://api.seudominio.com.br \
  -t datafood-front:small-v1 ./front-end
docker save datafood-back:small-v1 datafood-front:small-v1 | gzip > datafood-small-v1.tar.gz
scp -i /caminho/chave.pem datafood-small-v1.tar.gz ubuntu@IP_DA_EC2:~/
```

Você também pode publicar imagens em um registry e fazer `docker compose pull`.
Use uma tag por versão para permitir retorno à versão anterior. Mudança no
domínio da API exige rebuild do frontend.

## 2. Prepare a instância

Instale Docker Engine e Compose v2 pelo repositório oficial para Ubuntu, Git e
Python 3. Configure os domínios e portas conforme [deploy.md](deploy.md).
Na EC2, só o repositório backend é necessário para executar imagens prontas:

```bash
mkdir -p ~/datafood
cd ~/datafood
git clone https://github.com/DataFoood/back.git
cd back
gunzip -c ~/datafood-small-v1.tar.gz | sudo docker load
cp .env.prod.example .env.prod
chmod 600 .env.prod
nano .env.prod
```

Preencha segredos, domínios, origens e canais como no deploy geral. Acrescente:

```dotenv
BACKEND_IMAGE=datafood-back:small-v1
FRONTEND_IMAGE=datafood-front:small-v1
EMBEDDING_MODEL=nomic-embed-text:v1.5
SEMANTIC_SEARCH_ENABLED=True
```

O Compose fixa os limites de processos e de embeddings, independentemente dos
valores `WEB_WORKERS` e `SHINZOU_WORKERS` do template geral.

## 3. Suba e confira

```bash
sudo docker compose -f docker-compose.small.yml --env-file .env.prod config --quiet
sudo docker compose -f docker-compose.small.yml --env-file .env.prod up -d --no-build
sudo docker compose -f docker-compose.small.yml --env-file .env.prod ps -a
sudo docker compose -f docker-compose.small.yml --env-file .env.prod logs --tail=100 web worker shinzou ollama
curl -fsS https://api.seudominio.com.br/api/health/
sudo docker stats --no-stream
free -h
df -h
```

O `ollama-init` deve terminar com código 0; ele não é um daemon. O web faz as
migrações e a coleta de estáticos antes de receber tráfego. Worker, beat e
shinzou esperam o web saudável para acessar o banco com o schema pronto.

Crie o administrador sem disputar memória com tarefas em segundo plano:

```bash
sudo docker compose -f docker-compose.small.yml --env-file .env.prod stop worker beat
sudo docker compose -f docker-compose.small.yml --env-file .env.prod run --rm --no-deps worker python manage.py createsuperuser
sudo docker compose -f docker-compose.small.yml --env-file .env.prod start worker beat
```

Use a mesma sequência de parada/run/start para importação OSM ou
`reindex_restaurants --all`, trocando apenas o comando Django. Não rode esses
processos extras com `exec web`: eles disputariam o limite do servidor HTTP.
Para indexação normal, o endpoint administrativo enfileira o trabalho no worker.
Não crie contas demo em produção.

## Limitações e operação

- Em sobrecarga do motor, a API já retorna texto e filtros, sem afinidade.
  Para operar só com texto, defina `SEMANTIC_SEARCH_ENABLED=False`, recrie web,
  worker e beat e pare `shinzou` e `ollama`. Não há espera por timeout de busca
  nem indexação quando essa opção está desligada.
- O worker solo executa uma tarefa por vez: uma indexação grande pode atrasar
  promoções e outras tarefas. O polling do Telegram passa para 60 segundos.
- Redis usa `noeviction` para preservar o broker. Ao atingir a capacidade,
  escritas podem falhar; acompanhe filas e a recuperação da outbox.
- Os logs têm rotação. Defina também retenção e backup do banco fora da EC2.
  Os volumes usam os mesmos nomes lógicos da stack geral; mantenha o mesmo
  nome de projeto ao migrar uma instalação existente e faça backup antes.
- Swap pode amortecer picos, com custo de latência; não substitui RAM nem
  valida a capacidade. Não aumente todos os limites se a máquina estiver sob
  pressão: reduza carga e confirme o processo responsável.
- Não existe capacidade validada de usuários simultâneos para essa instalação.
  Mantenha `LOCAL_CAPACITY_CALIBRATED=False` até medir no servidor real.

Para atualizar: gere novas imagens fora da EC2, transfira/carregue, ajuste as
tags em `.env.prod` e execute novamente `up -d --no-build`. Guarde a versão
anterior e um backup restaurável. Migrações de banco podem exigir um plano
específico de retorno, além de trocar a imagem.
