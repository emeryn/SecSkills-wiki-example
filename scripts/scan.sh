#!/bin/sh
# Image and configuration scans. Reports go to reports/; exits non-zero on HIGH/CRITICAL findings.
# Images are scanned from `docker save` archives: the container socket is never mounted.
set -u
# Git Bash on Windows would otherwise rewrite container paths such as /run/secrets.
export MSYS_NO_PATHCONV=1

TRIVY_IMAGE="aquasec/trivy:0.67.2@sha256:e2b22eac59c02003d8749f5b8d9bd073b62e30fefaef5b7c8371204e0a4b0c08"
IMAGES="${BACKEND_IMAGE:-wiki-backend} ${FRONTEND_IMAGE:-wiki-frontend} ${DB_IMAGE:-wiki-db}"
WORKDIR="$(pwd -W 2>/dev/null || pwd)"
status=0

trivy() {
  docker run --rm -v "$WORKDIR:/work" -w /work -v wiki-trivy-cache:/root/.cache/trivy \
    "$TRIVY_IMAGE" --quiet "$@"
}

mkdir -p reports
for image in $IMAGES; do
  name="$(basename "$image")"
  docker save -o "reports/$name.tar" "$image" || { status=1; continue; }
  trivy image --input "reports/$name.tar" --scanners vuln,secret,misconfig \
    --severity HIGH,CRITICAL --exit-code 1 --format table \
    --output "reports/trivy-$name.txt"
  image_status=$?
  rm -f "reports/$name.tar"
  if [ "$image_status" -eq 0 ]; then
    printf 'trivy %-16s 0 high / 0 critical\n' "$name"
  else
    status=1
    printf 'trivy %-16s findings, see reports/trivy-%s.txt\n' "$name" "$name"
  fi
done

trivy config --severity HIGH,CRITICAL --exit-code 1 --output reports/trivy-config.txt . || status=1
printf 'trivy config: reports/trivy-config.txt\n'

# OpenSCAP needs SCAP content for the image's base OS (e.g. the CIS profile of SCAP Security
# Guide). Wolfi and Alpine bases have no upstream content, so the operator provides it.
if [ -n "${SCAP_CONTENT:-}" ] && command -v oscap-podman >/dev/null 2>&1; then
  for image in $IMAGES; do
    oscap-podman "$image" xccdf eval --profile "${SCAP_PROFILE:-cis}" \
      --report "reports/oscap-$(basename "$image").html" "$SCAP_CONTENT" || status=1
  done
elif [ -n "${SCAP_CONTENT:-}" ] && command -v oscap-docker >/dev/null 2>&1; then
  for image in $IMAGES; do
    oscap-docker image "$image" xccdf eval --profile "${SCAP_PROFILE:-cis}" \
      --report "reports/oscap-$(basename "$image").html" "$SCAP_CONTENT" || status=1
  done
else
  printf 'OpenSCAP: skipped (needs oscap-podman or oscap-docker and SCAP_CONTENT)\n'
fi

exit "$status"
