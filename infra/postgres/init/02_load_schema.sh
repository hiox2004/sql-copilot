#!/bin/bash
# Loads the schema and seed data from data/schema (mounted at /schema).
# Runs once, after 01_roles.sh, on first start of an empty data volume.
set -e
for f in /schema/*.sql; do
  echo "Loading $f"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
# Tables now exist: make sure the read-only role can read all of them.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${COPILOT_RO_USER};"
