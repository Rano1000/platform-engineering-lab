#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/supply-chain-common.sh
. "$SCRIPT_DIR/lib/supply-chain-common.sh"

GHCR_IMAGE=ghcr.io/rano1000/golden-path-api
EXPECTED_REPOSITORY=Rano1000/platform-engineering-lab

die() { printf 'ERROR %s\n' "$*" >&2; exit 1; }

publish() {
  artifact_directory=$1
  [ "${GITHUB_REPOSITORY:-}" = "$EXPECTED_REPOSITORY" ] || die 'publication is restricted to the source repository'
  [ "${GITHUB_EVENT_NAME:-}" = push ] || die 'publication is restricted to a push event'
  [ "${GITHUB_REF:-}" = refs/heads/main ] || die 'publication is restricted to main'
  [ "${GHCR_PUBLICATION_APPROVED:-}" = true ] || die 'first publication requires explicit GHCR_PUBLICATION_APPROVED repository-variable approval'
  [ -n "${GITHUB_TOKEN:-}" ] || die 'GITHUB_TOKEN is required'
  [ -f "$artifact_directory/.attestations-verified" ] || die 'cryptographic artifact verification marker is missing'
  archive_sha=$(cut -d ' ' -f 1 "$artifact_directory/golden-path-api.tar.sha256")
  marker=$(cat "$artifact_directory/.attestations-verified")
  [ "$marker" = "$archive_sha" ] || die 'artifact verification marker does not match the archive checksum'
  ARTIFACT_DIR=$artifact_directory
  export ARTIFACT_DIR
  "$SCRIPT_DIR/supply-chain.sh" load-artifact
  local_reference=$(image_reference)
  revision=$(docker image inspect "$local_reference" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$revision" = "${GITHUB_SHA:-}" ] || die 'OCI revision does not match the workflow revision'
  registry_tag=$GHCR_IMAGE:$APP_VERSION-$(short_revision)
  docker tag "$local_reference" "$registry_tag"
  printf '%s' "$GITHUB_TOKEN" | docker login ghcr.io --username "${GITHUB_ACTOR:-github-actions}" --password-stdin >/dev/null
  docker push "$registry_tag" >/dev/null
  repository_digest=$(docker image inspect "$registry_tag" --format '{{range .RepoDigests}}{{println .}}{{end}}' | awk -v image="$GHCR_IMAGE@" 'index($0,image)==1 {sub("^" image, ""); print; exit}')
  printf '%s\n' "$repository_digest" | grep -Eq '^sha256:[0-9a-f]{64}$' || die 'registry did not return a complete digest'
  remote_revision=$(docker image inspect "$GHCR_IMAGE@$repository_digest" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$remote_revision" = "$revision" ] || die 'registry image OCI revision differs from the source commit'
  printf 'image=%s\ndigest=%s\nrevision=%s\n' "$GHCR_IMAGE" "$repository_digest" "$revision"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf 'image=%s\ndigest=%s\nrevision=%s\n' "$GHCR_IMAGE" "$repository_digest" "$revision" >>"$GITHUB_OUTPUT"
  fi
}

self_test() {
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  if GITHUB_REPOSITORY=$EXPECTED_REPOSITORY GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main \
    GHCR_PUBLICATION_APPROVED=true GITHUB_TOKEN=test-token "$0" publish "$temporary" >/dev/null 2>&1; then
    die 'publication accepted unverified artifacts'
  fi
  printf '%s\n' 'PASS  publication refuses artifacts without cryptographic verification evidence.'
}

case ${1:-} in
  publish) [ "$#" -eq 2 ] || exit 2; publish "$2" ;;
  self-test) self_test ;;
  *) printf 'usage: %s {publish ARTIFACT_DIR|self-test}\n' "$0" >&2; exit 2 ;;
esac
