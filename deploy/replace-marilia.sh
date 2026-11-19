#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
web="${DATAFOOD_WEB_CONTAINER:-backend-web-1}"
db="${DATAFOOD_DB_CONTAINER:-backend-db-1}"
backup_root="${DATAFOOD_BACKUP_DIR:-$HOME/datafood-backups}"
data_file="$repo_root/data/marilia-osm-20261119.json"

test -f "$data_file"
(cd "$repo_root/data" && sha256sum --check marilia-osm-20261119.sha256)
if ! sudo docker exec "$web" python manage.py import_osm --help | grep -q -- '--replace'; then
  echo 'O container ainda precisa receber o backend com import_osm --replace.' >&2
  exit 1
fi

mkdir -p -- "$backup_root"
backup_file="$(mktemp "$backup_root/pre-marilia-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.dump")"
sudo docker exec "$db" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_file"
test -s "$backup_file"
sudo docker exec -i "$db" pg_restore --list < "$backup_file" > /dev/null
echo "Backup: $backup_file"

sudo docker cp "$data_file" "$web:/tmp/datafood-marilia-20261119.json"
sudo docker exec "$web" python manage.py import_osm --file /tmp/datafood-marilia-20261119.json --replace --dry-run
sudo docker exec "$web" python manage.py import_osm --file /tmp/datafood-marilia-20261119.json --replace
sudo docker exec "$web" python manage.py shell -c 'from restaurants.models import Restaurant; from users.models import User; print({"restaurantes_ativos": Restaurant.objects.count(), "contas_ativas": User.objects.count(), "cidades": list(Restaurant.objects.order_by("addresses__city").values_list("addresses__city", flat=True).distinct())})'
