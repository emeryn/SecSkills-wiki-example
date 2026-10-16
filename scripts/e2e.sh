#!/bin/sh
# End-to-end tests in Chromium against the running stack (`docker compose up -d` first).
# The test container joins the proxy network and forwards localhost:<port> to the proxy, so the
# browser uses the public URL and Origin checks, cookies and CSP behave as in production.
set -u
# Git Bash on Windows would otherwise rewrite container paths such as /run/secrets.
export MSYS_NO_PATHCONV=1

PROJECT="${COMPOSE_PROJECT_NAME:-wiki}"
PORT="${FRONTEND_PORT:-8443}"
IMAGE="mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27"
ROOT="$(pwd -W 2>/dev/null || pwd)"
ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-$(docker compose exec -T backend python -m app.cli admin-password 2>/dev/null | sed -n 's/^Password: //p')}"

docker run --rm --network "${PROJECT}_frontend_net" --ipc=host \
  -v "$ROOT:/repo" -w /repo/frontend/e2e \
  -e E2E_BASE_URL="https://localhost:$PORT" -e E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" -e PORT="$PORT" \
  -e E2E_SCREENSHOTS_DIR="${E2E_SCREENSHOTS_DIR:-}" -e HOST_OWNER="$(id -u):$(id -g)" \
  "$IMAGE" sh -c '
    node -e "require(\"net\").createServer(c => c.pipe(require(\"net\").connect(8443, \"frontend\")).pipe(c)).listen(process.env.PORT, \"127.0.0.1\")" &
    npm ci --no-audit >/dev/null && npx playwright test "$@"
    status=$?
    # Files written into the repository belong to the host user, not to the container root.
    [ -z "$E2E_SCREENSHOTS_DIR" ] || chown -R "$HOST_OWNER" "$E2E_SCREENSHOTS_DIR" 2>/dev/null
    exit $status
  ' e2e "$@"
