#!/bin/sh
set -eu

REPOSITORY=Rano1000/platform-engineering-lab

verify_checksum() {
  directory=$1
  checksum=$2
  (cd "$directory" && sha256sum --check --status "$checksum")
}

verify_artifacts() {
  directory=$1
  gh_binary=$2
  verify_checksum "$directory" golden-path-api.tar.sha256 || {
    printf '%s\n' 'ERROR image archive checksum verification failed.' >&2
    exit 1
  }
  verify_checksum "$directory" golden-path-api.cdx.json.sha256 || {
    printf '%s\n' 'ERROR SBOM checksum verification failed.' >&2
    exit 1
  }
  "$gh_binary" attestation verify "$directory/golden-path-api.tar" --repo "$REPOSITORY" >/dev/null
  "$gh_binary" attestation verify "$directory/golden-path-api.cdx.json" --repo "$REPOSITORY" >/dev/null
  printf '%s\n' 'PASS  archive and SBOM checksums and GitHub attestations are verified.'
}

verify_image() {
  reference=$1
  gh_binary=$2
  printf '%s\n' "$reference" | grep -Eq '^ghcr\.io/rano1000/golden-path-api@sha256:[0-9a-f]{64}$' || {
    printf '%s\n' 'ERROR image verification requires the approved repository and a complete digest.' >&2
    exit 1
  }
  "$gh_binary" attestation verify "oci://$reference" --repo "$REPOSITORY" >/dev/null
  printf '%s\n' "PASS  registry image attestation is verified for $reference."
}

self_test() {
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  printf '%s\n' archive >"$temporary/golden-path-api.tar"
  printf '%s\n' sbom >"$temporary/golden-path-api.cdx.json"
  (cd "$temporary" && sha256sum golden-path-api.tar >golden-path-api.tar.sha256)
  (cd "$temporary" && sha256sum golden-path-api.cdx.json >golden-path-api.cdx.json.sha256)
  verify_checksum "$temporary" golden-path-api.tar.sha256
  verify_checksum "$temporary" golden-path-api.cdx.json.sha256
  printf '%s\n' altered >>"$temporary/golden-path-api.tar"
  if verify_checksum "$temporary" golden-path-api.tar.sha256; then
    printf '%s\n' 'ERROR altered archive passed checksum verification.' >&2
    exit 1
  fi
  printf '%s\n' archive >"$temporary/golden-path-api.tar"
  printf '%s\n' altered >>"$temporary/golden-path-api.cdx.json"
  if verify_checksum "$temporary" golden-path-api.cdx.json.sha256; then
    printf '%s\n' 'ERROR altered SBOM passed checksum verification.' >&2
    exit 1
  fi
  printf '%s\n' 'PASS  altered archive and SBOM content is rejected before attestation verification.'
}

case ${1:-} in
  artifacts) [ "$#" -eq 3 ] || exit 2; verify_artifacts "$2" "$3" ;;
  image) [ "$#" -eq 3 ] || exit 2; verify_image "$2" "$3" ;;
  self-test) self_test ;;
  *) printf 'usage: %s {artifacts DIR GH_BIN|image IMAGE@DIGEST GH_BIN|self-test}\n' "$0" >&2; exit 2 ;;
esac
