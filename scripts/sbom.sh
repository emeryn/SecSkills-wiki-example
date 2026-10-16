#!/bin/sh
# CycloneDX SBOM per image; with COSIGN_KEY set, signs the images and attaches the SBOM as an
# attestation. Signing needs registry references (set BACKEND_IMAGE etc. and push first).
set -eu
# Git Bash on Windows would otherwise rewrite container paths such as /run/secrets.
export MSYS_NO_PATHCONV=1

TRIVY_IMAGE="aquasec/trivy:0.67.2@sha256:e2b22eac59c02003d8749f5b8d9bd073b62e30fefaef5b7c8371204e0a4b0c08"
COSIGN_IMAGE="ghcr.io/sigstore/cosign/cosign:v2.6.1@sha256:68839b7f13dac5a6744a5d8818e984dd39183374e37855c19e14d623d9bc9037"
IMAGES="${BACKEND_IMAGE:-wiki-backend} ${FRONTEND_IMAGE:-wiki-frontend} ${DB_IMAGE:-wiki-db}"
WORKDIR="$(pwd -W 2>/dev/null || pwd)"

mkdir -p sbom
for image in $IMAGES; do
  name="$(basename "$image" | cut -d: -f1)"
  docker save -o "sbom/$name.tar" "$image"
  docker run --rm -v "$WORKDIR:/work" -w /work -v wiki-trivy-cache:/root/.cache/trivy \
    "$TRIVY_IMAGE" image --input "sbom/$name.tar" --format cyclonedx --output "sbom/$name.cdx.json"
  rm -f "sbom/$name.tar"
  printf 'SBOM: sbom/%s.cdx.json\n' "$name"
done

if [ -z "${COSIGN_KEY:-}" ]; then
  printf 'Signing skipped: set COSIGN_KEY (and COSIGN_PASSWORD) with registry image references\n'
  exit 0
fi

key_dir="$(cd "$(dirname "$COSIGN_KEY")" && (pwd -W 2>/dev/null || pwd))"
key_file="$(basename "$COSIGN_KEY")"
docker_config="$(cd "${DOCKER_CONFIG:-$HOME/.docker}" && (pwd -W 2>/dev/null || pwd))"
for image in $IMAGES; do
  name="$(basename "$image" | cut -d: -f1)"
  cosign() {
    docker run --rm -e COSIGN_PASSWORD -v "$key_dir:/keys:ro" -v "$WORKDIR:/work" -w /work \
      -v "$docker_config:/root/.docker:ro" "$COSIGN_IMAGE" "$@"
  }
  cosign sign --yes --tlog-upload=false --key "/keys/$key_file" "$image"
  cosign attest --yes --tlog-upload=false --key "/keys/$key_file" --type cyclonedx \
    --predicate "sbom/$name.cdx.json" "$image"
  printf 'Signed and attested: %s\n' "$image"
done
