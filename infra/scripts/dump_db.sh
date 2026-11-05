#!/bin/bash
# Save the running database to a plain SQL file you can open, copy or restore anywhere.
# Usage (from repo root, Git Bash):  bash infra/scripts/dump_db.sh [name]
# Output: data/snapshots/<name>.sql   (default name: saas)
set -e
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
name="${1:-saas}"
mkdir -p data/snapshots
docker exec t2sql-postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl > "data/snapshots/${name}.sql"
echo "Wrote data/snapshots/${name}.sql ($(du -h "data/snapshots/${name}.sql" | cut -f1))"
