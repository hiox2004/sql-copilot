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

# Tables now exist: give the read-only role SELECT, but NOT on personal-data columns.
# The file is generated from the dictionary's pii flags (scripts/gen_column_grants.py).
psql -v ON_ERROR_STOP=1 -v ro_user="$COPILOT_RO_USER" --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" -f /schema/grants/copilot_ro.sql
