#!/bin/sh
# Pre-production checks, run after human validation: secret scan of the working tree and of the
# git history. Fails on any finding.
set -u
# Git Bash on Windows would otherwise rewrite container paths such as /run/secrets.
export MSYS_NO_PATHCONV=1

GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks:v8.28.0@sha256:cdbb7c955abce02001a9f6c9f602fb195b7fadc1e812065883f695d1eeaba854"
WORKDIR="$(pwd -W 2>/dev/null || pwd)"
status=0

gitleaks() {
  docker run --rm -v "$WORKDIR:/repo:ro" -w /repo "$GITLEAKS_IMAGE" "$@"
}

printf 'gitleaks: working tree\n'
gitleaks dir --no-banner --redact /repo || status=1

if [ -d .git ]; then
  printf 'gitleaks: git history\n'
  gitleaks git --no-banner --redact /repo || status=1
else
  printf 'gitleaks: git history skipped (not a git repository)\n'
fi

for tracked in CLAUDE.md .claude; do
  if [ -d .git ] && git ls-files --error-unmatch "$tracked" >/dev/null 2>&1; then
    printf 'FAIL: %s is tracked by git\n' "$tracked"
    status=1
  fi
done

exit "$status"
