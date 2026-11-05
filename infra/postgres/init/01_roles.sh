#!/bin/bash
# Runs once, on first start of an empty data volume.
# Creates the read-only role the copilot uses. It can SELECT but never write.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE ${COPILOT_RO_USER} LOGIN PASSWORD '${COPILOT_RO_PASSWORD}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${COPILOT_RO_USER};
GRANT USAGE ON SCHEMA public TO ${COPILOT_RO_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${COPILOT_RO_USER};
ALTER ROLE ${COPILOT_RO_USER} SET default_transaction_read_only = on;
ALTER ROLE ${COPILOT_RO_USER} SET statement_timeout = '10s';
SQL
