#!/usr/bin/env bash
# Uso: scripts/verify-backup.sh COMPOSE_FILE ARQUIVO_NOVO.dump [COMPOSE_PROJECT]
# Cria backup e testa a restauração em banco temporário; nunca restaura no ativo.
set -euo pipefail
compose_file="${1:?Informe o arquivo Compose}"
backup_path="${2:?Informe um caminho novo para o backup fora do checkout}"
compose_project="${3:-datafood}"
[[ ! -e "$backup_path" ]] || { echo 'O arquivo de destino já existe.' >&2; exit 1; }
restore_db="datafood_verify_${$}_$(date +%s)"
created=0
compose=(docker compose -p "$compose_project" -f "$compose_file")
cleanup() {
  if [[ "$created" == 1 ]]; then
    "${compose[@]}" exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$1"' sh "$restore_db"
  fi
}
trap cleanup EXIT
# noclobber protege também contra corrida no arquivo de destino.
(set -o noclobber; "${compose[@]}" exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_path")
"${compose[@]}" exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$restore_db"
created=1
"${compose[@]}" exec -T db sh -c 'exec pg_restore --exit-on-error -U "$POSTGRES_USER" -d "$1"' sh "$restore_db" < "$backup_path"
"${compose[@]}" exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "SELECT count(*) AS restaurants_restored FROM restaurants_restaurant;"' sh "$restore_db"
echo 'Backup criado e restauração verificada em banco temporário.'
