# Atualização do backend na VPS

Executar **após o merge do PR do backend na main**. O registro de operação
anterior identifica `/home/ubuntu/backend`, `docker-compose.prod.yml`, `.env.prod`
e os serviços `db`, `web`, `worker`, `beat`, `shinzou`, `ollama` e `caddy`.
Não havia frontend no servidor. A sequência abaixo atualiza só API e workers.
Se a instalação usa outro diretório, arquivo Compose ou nome de projeto,
utilize os mesmos da stack em execução; não crie outro projeto Compose.

## Atualizar código e configuração

```bash
cd /home/ubuntu/backend
git switch main
git pull --ff-only origin main
nano .env.prod
```

Acrescente esta variável, preservando as demais configurações e segredos:

```dotenv
CHAT_CATALOG_MODE=True
```

Ela ativa as prévias, o refinamento e a surpresa contextual. O fluxo anterior
permanece disponível com `False`; a mudança exige recriar os contêineres.
Mantenha os valores já utilizados para `CHAT_GENERATION_ENABLED`, `CHAT_MODEL`,
`SEMANTIC_SEARCH_ENABLED` e o hash do cupom. Na operação registrada, o gerador
era `qwen3:0.6b` e a busca vetorial estava desativada. Esta atualização não
exige trocar nem baixar um modelo maior. O front precisa do PR correspondente.

## Backup e atualização

O bloco faz uma pausa na API durante migrações/carga. A migração 0014 remove
avaliações de contas encerradas, conforme solicitado; trocar a imagem antiga
não recupera esses dados. O dump fica privado e é validado antes da parada.
Execute em Bash, interrompendo a sequência se um comando falhar:

```bash
set -e
umask 077
dc() { sudo docker compose -f docker-compose.prod.yml --env-file .env.prod "$@"; }

mkdir -p "$HOME/datafood-backups"
TASK_BACKUP="$HOME/datafood-backups/pre-review-$(date -u +%Y%m%dT%H%M%SZ).dump"
dc exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TASK_BACKUP"
test -s "$TASK_BACKUP"
dc exec -T db pg_restore --list < "$TASK_BACKUP" > /dev/null
printf 'Backup salvo em: %s\n' "$TASK_BACKUP"

dc build web worker beat
dc stop web worker beat
dc run --rm --no-deps worker python manage.py migrate --noinput
dc run --rm --no-deps worker python manage.py load_catalog
dc up -d --no-deps --wait web worker beat

dc ps
dc logs --tail=60 web worker beat
```

A imagem agora inclui `catalog/`. `load_catalog` usa os snapshots versionados,
sem chamadas pagas ou coleta externa; é repetível, não executa `--replace` e
preserva contas, edições do dono e cadastros removidos. A quantidade final na
VPS depende dos dados já existentes; em banco vazio de verificação foram 194
cadastros, 151 com capa e 185 com endereço. Se uma etapa após a parada falhar,
consulte o erro e preserve o backup antes de retomar; não execute as etapas
seguintes ignorando a falha.

## Conferir

```bash
dc exec -T web python manage.py showmigrations restaurants
dc exec -T web python manage.py shell -c 'from django.conf import settings; from restaurants.models import Restaurant; print({"modo_catalogo": settings.CHAT_CATALOG_MODE, "restaurantes_ativos": Restaurant.objects.count(), "capas_preenchidas": Restaurant.objects.exclude(cover_image="").count()})'
```

No site, conferir login, selo PRO, prévia de restaurantes e a sequência
`Quero pizza em Marília` → `Me surpreenda`. A cozinha e a cidade precisam ser
preservadas. Abrir a seleção, recusar um card, escolher outro e conferir o
favorito. A versão do front deve ser atualizada pelo deploy habitual dele.

Se a instalação já usa `SEMANTIC_SEARCH_ENABLED=True`, reconstruir também a
imagem do `shinzou` e reindexar o catálogo em uma janela de baixo uso. Para o
modo somente catálogo/texto registrado na VPS, reindexar não é necessário.
Não rodar `seed_demo`, `import_osm --replace` ou `docker compose down -v` como
parte desta atualização.
