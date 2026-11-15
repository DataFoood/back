# Deploy (produção)

Stack completa num servidor com Docker: API (gunicorn), shinzou, worker/beat,
Postgres+pgvector, Redis, Ollama, frontend Next.js e **Caddy** na frente com
HTTPS automático (Let's Encrypt). Só as portas 80/443 ficam expostas.

## Pré-requisitos

Para EC2 t3.small (2 GiB), use [deploy-small.md](deploy-small.md) e o Compose
específico. A configuração abaixo é a stack geral, com mais processos.

- Servidor Linux com Docker + Compose v2 (≥ 4 GB RAM — o Ollama usa ~1 GB).
- Dois domínios apontando (DNS A/AAAA) para o servidor, ex.:
  `app.seudominio.com.br` (front) e `api.seudominio.com.br` (API).
- Os dois repositórios lado a lado: `./back` e `./front-end`
  (ou ajuste `FRONTEND_PATH`).

## Passo a passo
```bash
cd back
cp .env.prod.example .env.prod
# preencha: SECRET_KEY, SHINZOU_SERVICE_TOKEN, DB_PASS, domínios, CORS/CSRF
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # gera segredos

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```
A primeira subida baixa o modelo de embeddings (alguns minutos). O `web` roda
`migrate` e `collectstatic` sozinho ao iniciar.

```bash
# admin
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py createsuperuser
# (opcional) restaurantes de demonstração + embeddings
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py seed_demo
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py reindex_restaurants
```
> `seed_demo --demo-users` cria contas com senha conhecida — **não use em produção**.

## Checklist
- [ ] CI do commit aprovado: testes, auditoria de dependências, migrações,
      OpenAPI, checks Django e imagem Docker. Localmente: `uv sync --frozen`,
      `uv run pip-audit` e os comandos de teste do README.
- [ ] `DEBUG=False`, `SECRET_KEY` e `SHINZOU_SERVICE_TOKEN` longos e aleatórios.
- [ ] `ALLOWED_HOSTS` = domínio da API + `web` (chamadas internas) + `localhost` (healthcheck do container).
- [ ] `CORS_ALLOWED_ORIGINS` = `https://<APP_DOMAIN>`; `CSRF_TRUSTED_ORIGINS` = `https://<API_DOMAIN>`.
- [ ] `DB_PASS` forte; backups do volume `postgres_data` (ex.: `pg_dump` diário).
- [ ] `NUM_PROXIES=1` (o compose já define para o `web`): sem isso o rate
      limit de login usa um header forjável ou junta todo mundo num IP só.
- [ ] `https://<API_DOMAIN>/api/health/` responde `{"status": "ok"}`.
- [ ] O frontend é buildado com `NEXT_PUBLIC_API_URL=https://<API_DOMAIN>`
      (o compose já passa isso); mudou o domínio → rebuild do `frontend`.
- [ ] Conferir os workers reais no log de inicialização do Gunicorn; o comando
      usa `exec` para entregar sinais de parada ao processo do servidor e
      mantém `--workers`, `--timeout` e `--access-logfile` na mesma chamada.
- [ ] Validar em homologação: login/refresh por cookie, busca com catálogo e
      modelo reais, envio para contas controladas nos canais habilitados,
      backup restaurável e procedimento de retorno.
- [ ] Medir capacidade na instalação de destino antes de definir
      `LOCAL_CAPACITY_CALIBRATED=True`; manter `SHOW_DEMO_RESTAURANTS=False`.

Checks locais e CI não comprovam DNS, certificados públicos, credenciais de
canais, qualidade do catálogo ou capacidade do servidor. Os critérios do
piloto real continuam em [implementation-status.md](implementation-status.md).

## Atualizar
```bash
git pull && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

## Sem Caddy (proxy/TLS próprio)
Remova o serviço `caddy`, publique `web:8000` e `frontend:3000` para o seu
proxy e mantenha o cabeçalho `X-Forwarded-Proto: https`. Se o proxy já
redireciona http→https, `SECURE_SSL_REDIRECT=False`. Ajuste `NUM_PROXIES`
para o número de proxies confiáveis entre o cliente e o Django, e garanta
que o proxy **sobrescreve** (não repassa) o `X-Forwarded-For` recebido.
