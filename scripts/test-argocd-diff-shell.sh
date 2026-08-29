#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH='' cd "$SCRIPT_DIR/.." && pwd)
EXPECTED_CONTEXT=kind-platform-engineering-lab
# shellcheck source=SCRIPTDIR/lib/gitops-common.sh
. "$SCRIPT_DIR/lib/gitops-common.sh"

temporary=$(mktemp -d "${TMPDIR:-/tmp}/argocd diff shell.XXXXXX")
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

run_argocd_core() {
  printf '\n===== apps/Deployment platform-apps/golden-path-golden-path-api ======\n1c1\n< old\n---\n> new\n'
  return 20
}

mkdir "$temporary/allowed" "$temporary/operational"
run_guarded_argocd_diff child '' '' "$temporary/allowed" app diff golden-path-api >/dev/null

run_argocd_core() {
  printf '%s\n' 'authentication failed' >&2
  return 2
}

failure_status=0
run_guarded_argocd_diff child '' '' "$temporary/operational" app diff golden-path-api \
  >"$temporary/operational.stdout" 2>"$temporary/operational.stderr" || failure_status=$?
[ "$failure_status" -eq 2 ] || {
  printf '%s\n' 'FAIL  operational Argo error passed guarded diff.' >&2
  exit 1
}
grep -F 'Argo operational failure (exit 2): authentication failed' "$temporary/operational.stderr" >/dev/null

printf '%s\n' 'PASS  POSIX set -e accepts only validated Argo difference status and preserves operational failures.'
