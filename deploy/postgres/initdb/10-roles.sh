#!/bin/sh
# Runs once, on an empty data directory. Creates the migration owner and the runtime DML-only
# role; the application never connects as superuser.
set -eu

owner_pw="$(cat /run/secrets/db/owner_password)"
runtime_pw="$(cat /run/secrets/db/runtime_password)"

psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  -v owner_pw="$owner_pw" -v runtime_pw="$runtime_pw" <<'SQL'
CREATE ROLE app_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'owner_pw';
CREATE ROLE app_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'runtime_pw';
ALTER ROLE app_owner SET lock_timeout = '10s';
ALTER ROLE app_runtime SET statement_timeout = '5s';
ALTER ROLE app_runtime SET idle_in_transaction_session_timeout = '30s';

CREATE DATABASE app OWNER app_owner;
REVOKE ALL ON DATABASE app FROM PUBLIC;
GRANT CONNECT ON DATABASE app TO app_owner, app_runtime;

\connect app
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_runtime;
SQL
