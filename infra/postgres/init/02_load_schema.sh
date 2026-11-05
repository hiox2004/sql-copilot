#!/bin/bash
# Loads the schema, seed data and consistency checks from data/schema (mounted at /schema).
# Runs once, after 01_roles.sh, on first start of an empty data volume.
# Files run in name order: 01_schema, 02_schema_extra, 03_seed_core, 04_seed_extra, 99_checks.
# If 99_checks.sql finds inconsistent data it raises an error and the whole init fails.
set -e

# The pinned "today" for all seed/check dates. Override with REF_NOW in the environment.
REF_NOW="${REF_NOW:-2026-11-05 12:00:00+00}"

for f in /schema/*.sql; do
  echo "Loading $f (ref_now=$REF_NOW)"
  psql -v ON_ERROR_STOP=1 -v ref_now="'${REF_NOW}'" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done

# Tables now exist: make sure the read-only role can read all of them.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${COPILOT_RO_USER};"
