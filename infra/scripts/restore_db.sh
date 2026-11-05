#!/bin/bash
# Load a snapshot into a database. Defaults to a SCRATCH copy so you can experiment
# (INSERT/UPDATE/DELETE, broken queries) without touching the real 'saas' database.
# Usage:  bash infra/scripts/restore_db.sh [snapshot.sql] [target_db]
#   defaults: data/snapshots/saas.sql  ->  saas_scratch
# Re-running DROPS and recreates the target, i.e. resets the scratch copy.
set -e
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
file="${1:-data/snapshots/saas.sql}"
target="${2:-saas_scratch}"
if [ "$target" = "$POSTGRES_DB" ]; then
  echo "Refusing to overwrite the main database '$POSTGRES_DB'. Pick another target name." >&2
  exit 1
fi
[ -f "$file" ] || { echo "Snapshot not found: $file (run infra/scripts/dump_db.sh first)" >&2; exit 1; }
docker exec t2sql-postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$target\" WITH (FORCE)" -c "CREATE DATABASE \"$target\""
docker exec -i t2sql-postgres psql -U "$POSTGRES_USER" -d "$target" -v ON_ERROR_STOP=1 -q < "$file" > /dev/null
echo "Restored $file into database '$target'. Tables: $(docker exec t2sql-postgres psql -U "$POSTGRES_USER" -d "$target" -tAc "select count(*) from information_schema.tables where table_schema='public'")"
