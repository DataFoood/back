# Deploy (produção)

Stack completa num servidor com Docker: API (gunicorn), shinzou, worker/beat,
Postgres+pgvector, Redis, Ollama, frontend Next.js e **Caddy** na frente com
HTTPS automático (Let's Encrypt). Só as portas 80/443 ficam expostas.

## Pré-requisitos
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
- [ ] `DEBUG=False`, `SECRET_KEY` e `SHINZOU_SERVICE_TOKEN` longos e aleatórios.
- [ ] `ALLOWED_HOSTS` = domínio da API (+ `web`, usado internamente).
- [ ] `CORS_ALLOWED_ORIGINS` = `https://<APP_DOMAIN>`; `CSRF_TRUSTED_ORIGINS` = `https://<API_DOMAIN>`.
- [ ] `DB_PASS` forte; backups do volume `postgres_data` (ex.: `pg_dump` diário).
- [ ] `https://<API_DOMAIN>/api/health/` responde `{"status": "ok"}`.
- [ ] O frontend é buildado com `NEXT_PUBLIC_API_URL=https://<API_DOMAIN>`
      (o compose já passa isso); mudou o domínio → rebuild do `frontend`.

## Atualizar
```bash
git pull && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

## Sem Caddy (proxy/TLS próprio)
Remova o serviço `caddy`, publique `web:8000` e `frontend:3000` para o seu
proxy e mantenha o cabeçalho `X-Forwarded-Proto: https`. Se o proxy já
redireciona http→https, `SECURE_SSL_REDIRECT=False`.
