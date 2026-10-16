#!/bin/sh
# PostgreSQL refuses a private key it does not own, and the secrets volume is read-only and
# owned by the init user, so the key is copied to tmpfs with the database user as owner.
set -eu

install -m 0600 /run/secrets/db/server.key /tmp/server.key

exec docker-entrypoint.sh postgres \
  -c listen_addresses='*' \
  -c hba_file=/etc/postgresql/pg_hba.conf \
  -c ssl=on \
  -c ssl_cert_file=/run/secrets/db/server.crt \
  -c ssl_key_file=/tmp/server.key \
  -c ssl_min_protocol_version=TLSv1.3 \
  -c password_encryption=scram-sha-256 \
  -c log_connections=on \
  -c log_disconnections=on \
  -c log_line_prefix='%m [%p] %q%u@%d '
