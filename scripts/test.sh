#!/bin/sh
# Backend tests against an ephemeral PostgreSQL (tmpfs, no network: the test container joins the
# database's network namespace and connects to localhost), then frontend tests.
# Extra arguments are passed to pytest.
set -u
# Git Bash on Windows would otherwise rewrite container paths such as /run/secrets.
export MSYS_NO_PATHCONV=1

# The application database image (pgvector included), started without its TLS entrypoint.
DB_IMAGE="wiki-db-test"
DB="wiki-test-db"
status=0

docker build -q -f backend/Dockerfile --target test -t wiki-backend-test . >/dev/null || exit 1
docker build -q -f deploy/postgres/Dockerfile -t "$DB_IMAGE" . >/dev/null || exit 1
docker rm -f "$DB" >/dev/null 2>&1
docker run -d --rm --name "$DB" --network none --tmpfs /var/lib/postgresql/data \
  --tmpfs /docker-entrypoint-initdb.d -e PGDATA=/var/lib/postgresql/data/pgdata -e POSTGRES_HOST_AUTH_METHOD=trust \
  --entrypoint docker-entrypoint.sh "$DB_IMAGE" postgres >/dev/null || exit 1
tries=0
until docker exec "$DB" pg_isready -q -h 127.0.0.1 -U postgres; do
  tries=$((tries + 1))
  [ "$tries" -gt 30 ] && { echo "Test database did not start"; docker rm -f "$DB" >/dev/null; exit 1; }
  sleep 1
done

docker run --rm --network "container:$DB" \
  -e TEST_DATABASE_ADMIN_URL="postgresql+psycopg://postgres@127.0.0.1/postgres" \
  wiki-backend-test pytest "$@" || status=1
docker rm -f "$DB" >/dev/null

if [ "$#" -eq 0 ]; then
  docker build -q -f frontend/Dockerfile --target test -t wiki-frontend-test . >/dev/null || exit 1
  docker run --rm --network none wiki-frontend-test npm test || status=1
fi
exit "$status"
