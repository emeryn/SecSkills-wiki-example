#!/bin/sh
# Checks the running stack through the reverse proxy: TLS policy, security headers, limits, health.
# Runs curl in a container on the proxy network; the generated CA is read from the secrets volume.
set -u
# Git Bash on Windows would otherwise rewrite container paths such as /run/secrets.
export MSYS_NO_PATHCONV=1

PROJECT="${COMPOSE_PROJECT_NAME:-wiki}"
CURL_IMAGE="curlimages/curl:8.17.0@sha256:935d9100e9ba842cdb060de42472c7ca90cfe9a7c96e4dacb55e79e560b3ff40"
BASE="https://localhost:8443"
failures=0

curl_proxy() {
  docker run --rm --network "${PROJECT}_frontend_net" --group-add 101 \
    -v "${PROJECT}_secrets:/run/secrets:ro" "$CURL_IMAGE" \
    --silent --max-time 10 --connect-to localhost:8443:frontend:8443 \
    --cacert /run/secrets/tls/tls.crt "$@"
}

status_of() {
  curl_proxy --output /dev/null --write-out '%{http_code}' "$@"
}

result() {
  if [ "$1" -eq 0 ]; then
    printf 'ok    %s\n' "$2"
  else
    printf 'FAIL  %s\n' "$2"
    failures=$((failures + 1))
  fi
}

contains() {
  printf '%s' "$1" | grep -qi -- "$2"
}

curl_proxy --tlsv1.3 --fail --output /dev/null "$BASE/"
result $? "index served over TLS 1.3 with a valid certificate chain"

curl_proxy --tlsv1.2 --tls-max 1.2 --output /dev/null "$BASE/"
[ $? -ne 0 ]
result $? "TLS 1.2 refused"

curl_proxy --curves X25519MLKEM768 --fail --output /dev/null "$BASE/"
result $? "hybrid post-quantum key exchange X25519MLKEM768"

headers="$(curl_proxy --head "$BASE/")"
for expected in \
  "^strict-transport-security: max-age=63072000" \
  "^content-security-policy: default-src 'self'" \
  "^content-security-policy:.*require-trusted-types-for 'script'" \
  "^content-security-policy:.*frame-ancestors 'none'" \
  "^x-content-type-options: nosniff" \
  "^x-frame-options: DENY" \
  "^referrer-policy: no-referrer" \
  "^permissions-policy: " \
  "^cross-origin-opener-policy: same-origin" \
  "^cross-origin-resource-policy: same-origin"; do
  contains "$headers" "$expected"
  result $? "header ${expected#^}"
done
contains "$headers" "^server: .*[0-9]"
[ $? -ne 0 ]
result $? "server version not disclosed"

health="$(curl_proxy --include "$BASE/api/v1/health")"
contains "$health" '"status":"ok"'
result $? "API health ok (backend reaches PostgreSQL over TLS)"
contains "$health" "^cache-control: no-store"
result $? "API responses not cached"
contains "$health" "^x-request-id: [0-9a-f]"
result $? "API responses carry a request id"

[ "$(status_of "$BASE/spaces/eng/pages/home")" = 200 ]
result $? "client-side routes fall back to index.html"

[ "$(status_of "$BASE/assets/index.js.map")" = 404 ]
result $? "source maps not served"

[ "$(status_of -X POST -H 'Content-Length: 12000000' --data 'x' "$BASE/api/v1/health")" = 413 ]
result $? "proxy rejects bodies over 11 MB (10 MB attachments plus multipart envelope)"

api_limit_status="$(head -c 3000000 /dev/zero | docker run --rm -i \
  --network "${PROJECT}_frontend_net" --group-add 101 -v "${PROJECT}_secrets:/run/secrets:ro" \
  "$CURL_IMAGE" --silent --max-time 20 --connect-to localhost:8443:frontend:8443 \
  --cacert /run/secrets/tls/tls.crt --output /dev/null --write-out '%{http_code}' \
  -X POST --data-binary @- "$BASE/api/v1/health")"
[ "$api_limit_status" = 413 ]
result $? "API rejects bodies over its own 2 MiB limit"

if [ "$failures" -gt 0 ]; then
  printf '%d check(s) failed\n' "$failures"
  exit 1
fi
printf 'All smoke checks passed\n'
