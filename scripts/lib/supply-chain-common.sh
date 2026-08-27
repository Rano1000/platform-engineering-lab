#!/bin/sh

PROJECT_ROOT=$(CDPATH='' cd "$SCRIPT_DIR/.." && pwd)
APP_VERSION=0.1.0
APP_IMAGE=golden-path-api
ARTIFACT_DIR=${ARTIFACT_DIR:-$PROJECT_ROOT/.artifacts/supply-chain}
IMAGE_ARCHIVE=$ARTIFACT_DIR/golden-path-api.tar
IMAGE_CHECKSUM=$IMAGE_ARCHIVE.sha256
SBOM=$ARTIFACT_DIR/golden-path-api.cdx.json
SCAN_REPORT=$ARTIFACT_DIR/trivy-vulnerabilities.json
SCAN_SUMMARY=$ARTIFACT_DIR/scan-summary.json
TRIVY_METADATA=$ARTIFACT_DIR/trivy-metadata.json
SBOM_METADATA=$ARTIFACT_DIR/sbom-metadata.json
POLICY=$PROJECT_ROOT/config/supply-chain/vulnerability-exceptions.json
TRIVY_VERSION=0.74.0
TRIVY_IMAGE=ghcr.io/aquasecurity/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
LOCK_COMPILER_IMAGE=platform-engineering-lab/pip-tools:7.6.1

die() {
  printf 'ERROR %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command '$1' is unavailable."
}

full_revision() {
  git -C "$PROJECT_ROOT" rev-parse HEAD
}

short_revision() {
  full_revision | cut -c1-12
}

image_reference() {
  printf '%s:%s-%s\n' "$APP_IMAGE" "$APP_VERSION" "$(short_revision)"
}

prepare_artifacts() {
  mkdir -p "$ARTIFACT_DIR"
}

run_trivy() {
  require_command docker
  prepare_artifacts
  mkdir -p "$ARTIFACT_DIR/trivy-cache"
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$PROJECT_ROOT:/workspace:ro" \
    -v "$ARTIFACT_DIR:/artifacts" \
    -v "$ARTIFACT_DIR/trivy-cache:/root/.cache/trivy" \
    "$TRIVY_IMAGE" "$@"
}

record_trivy_metadata() {
  run_trivy version --format json >"$TRIVY_METADATA"
}
