#!/bin/sh
# README screenshots: starts an ephemeral stack (its own project, port and volumes), seeds it with
# the demo content of frontend/e2e/fixtures/, captures docs/screenshots/*.png, then removes it.
set -u

export COMPOSE_PROJECT_NAME="wiki-screenshots"
export FRONTEND_PORT="${SCREENSHOTS_PORT:-18443}"
export BACKEND_PUBLIC_URL="https://localhost:$FRONTEND_PORT"
trap 'docker compose down -v --remove-orphans >/dev/null 2>&1' EXIT INT TERM

docker compose down -v --remove-orphans >/dev/null 2>&1
docker compose up -d --build || exit 1

printf 'Waiting for the backend'
password=""
for _ in $(seq 1 90); do
  password="$(docker compose exec -T backend python -m app.cli admin-password 2>/dev/null | sed -n 's/^Password: //p')"
  [ -n "$password" ] && break
  printf '.'
  sleep 2
done
echo
[ -n "$password" ] || { echo "The stack did not become ready."; docker compose ps; exit 1; }

E2E_ADMIN_PASSWORD="$password" E2E_SCREENSHOTS_DIR=/repo/docs/screenshots \
  sh scripts/e2e.sh --project=screenshots || exit 1
ls -l docs/screenshots
