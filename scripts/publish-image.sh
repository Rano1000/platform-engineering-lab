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
  [ "${GITHUB_EVENT_NAME:-}" = workflow_dispatch ] || die 'publication requires the manual verified-artifact workflow'
  [ "${GITHUB_REF:-}" = refs/heads/main ] || die 'publication is restricted to main'
  [ "${GHCR_PUBLICATION_APPROVED:-}" = true ] || die 'first publication requires explicit GHCR_PUBLICATION_APPROVED repository-variable approval'
  revision=$(full_revision)
  expected_confirmation=$EXPECTED_REPOSITORY/$revision/${EXPECTED_ARCHIVE_SHA256:-}
  [ "${PUBLICATION_CONFIRMATION:-}" = "$expected_confirmation" ] || die 'typed publication confirmation is invalid'
  [ -n "${GITHUB_TOKEN:-}" ] || die 'GITHUB_TOKEN is required'
  [ -f "$artifact_directory/.attestations-verified" ] || die 'cryptographic artifact verification marker is missing'
  archive_sha=$(cut -d ' ' -f 1 "$artifact_directory/golden-path-api.tar.sha256")
  [ "$archive_sha" = "${EXPECTED_ARCHIVE_SHA256:-}" ] || die 'archive checksum differs from the approved request'
  marker=$(cat "$artifact_directory/.attestations-verified")
  [ "$marker" = "$archive_sha" ] || die 'artifact verification marker does not match the archive checksum'
  ARTIFACT_DIR=$artifact_directory
  export ARTIFACT_DIR
  "$SCRIPT_DIR/supply-chain.sh" load-artifact
  local_reference=$(image_reference)
  configured_revision=$(docker image inspect "$local_reference" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$configured_revision" = "$revision" ] || die 'OCI revision does not match the approved source revision'
  registry_tag=$GHCR_IMAGE:$APP_VERSION-$(short_revision)
  printf '%s' "$GITHUB_TOKEN" | docker login ghcr.io --username "${GITHUB_ACTOR:-github-actions}" --password-stdin >/dev/null
  if docker manifest inspect "$registry_tag" >/dev/null 2>&1; then
    die "immutable registry tag already exists: $registry_tag"
  fi
  docker tag "$local_reference" "$registry_tag"
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
  common_revision=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  common_checksum=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  if GITHUB_REPOSITORY=$EXPECTED_REPOSITORY GITHUB_EVENT_NAME=workflow_dispatch \
    GITHUB_REF=refs/heads/main GITHUB_TOKEN=test-token \
    SOURCE_REVISION=$common_revision EXPECTED_ARCHIVE_SHA256=$common_checksum \
    PUBLICATION_CONFIRMATION=$EXPECTED_REPOSITORY/$common_revision/$common_checksum \
    "$0" publish "$temporary" >/dev/null 2>&1; then
    die 'publication accepted a missing approval variable'
  fi
  if GITHUB_REPOSITORY=$EXPECTED_REPOSITORY GITHUB_EVENT_NAME=workflow_dispatch \
    GITHUB_REF=refs/heads/main GHCR_PUBLICATION_APPROVED=true GITHUB_TOKEN=test-token \
    SOURCE_REVISION=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    EXPECTED_ARCHIVE_SHA256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
    PUBLICATION_CONFIRMATION=invalid \
    "$0" publish "$temporary" >/dev/null 2>&1; then
    die 'publication accepted an incorrect typed confirmation'
  fi
  printf '%s\n' 'PASS  publication rejects missing approval and incorrect typed confirmation.'
}

case ${1:-} in
  publish) [ "$#" -eq 2 ] || exit 2; publish "$2" ;;
  self-test) self_test ;;
  *) printf 'usage: %s {publish ARTIFACT_DIR|self-test}\n' "$0" >&2; exit 2 ;;
esac
