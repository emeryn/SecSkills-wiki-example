#!/bin/sh
# Restores the newest backup (or BACKUP=<name>) into a throwaway PostgreSQL and verifies it:
# row counts, attachment checksums, audit hash chain, master key. Nothing touches the live stack.
# The scratch database runs without network; the check container joins its network namespace and
# reads the backups and secrets volumes read-only.
set -u
# Git Bash on Windows would otherwise rewrite container paths such as /run/secrets.
export MSYS_NO_PATHCONV=1

DOCKER="${DOCKER:-docker}"
PROJECT="${COMPOSE_PROJECT_NAME:-wiki}"
BACKEND_IMAGE="${BACKEND_IMAGE:-wiki-backend}"
# The application database image (pgvector included), started without its TLS entrypoint.
DB_IMAGE="${DB_IMAGE:-wiki-db}"
DB="wiki-restore-test-db"

"$DOCKER" volume inspect "${PROJECT}_backups" >/dev/null 2>&1 || {
  echo "No backups volume (${PROJECT}_backups): run 'make backup' first."; exit 1; }

"$DOCKER" rm -f "$DB" >/dev/null 2>&1
"$DOCKER" run -d --rm --name "$DB" --network none --tmpfs /var/lib/postgresql/data \
  --tmpfs /docker-entrypoint-initdb.d -e PGDATA=/var/lib/postgresql/data/pgdata -e POSTGRES_HOST_AUTH_METHOD=trust \
  --entrypoint docker-entrypoint.sh "$DB_IMAGE" postgres >/dev/null || exit 1
tries=0
until "$DOCKER" exec "$DB" pg_isready -q -h 127.0.0.1 -U postgres; do
  tries=$((tries + 1))
  [ "$tries" -gt 30 ] && { echo "Scratch database did not start"; "$DOCKER" rm -f "$DB" >/dev/null; exit 1; }
  sleep 1
done

set -- python -m app.cli restore-test --admin-url "postgresql+psycopg://postgres@127.0.0.1/postgres"
[ -n "${BACKUP:-}" ] && set -- "$@" --name "$BACKUP"
"$DOCKER" run --rm --network "container:$DB" --read-only --tmpfs /tmp --cap-drop ALL \
  --security-opt no-new-privileges:true \
  -v "${PROJECT}_backups:/var/lib/wiki/backups:ro" \
  -v "${PROJECT}_secrets:/run/secrets:ro" \
  "$BACKEND_IMAGE" "$@"
status=$?
"$DOCKER" rm -f "$DB" >/dev/null
exit "$status"
