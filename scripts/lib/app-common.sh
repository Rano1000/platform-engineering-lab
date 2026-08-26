#!/bin/sh

APP_NAME=golden-path-api
APP_VERSION=0.1.0
APP_RELEASE=golden-path
APP_NAMESPACE=platform-apps
APP_REPLICAS=2
APP_CHART=$REPOSITORY_ROOT/charts/golden-path-api
APP_CONTEXT=$REPOSITORY_ROOT/applications/golden-path-api
APP_DEPLOYMENT=$APP_RELEASE-$APP_NAME
APP_SERVICE=$APP_DEPLOYMENT

GATEWAY_API_VERSION=v1.6.1
GATEWAY_API_URL=https://github.com/kubernetes-sigs/gateway-api/releases/download/$GATEWAY_API_VERSION/standard-install.yaml
GATEWAY_API_SHA256=24d931f22abd8e40c973264319ead7cfa09d0fb7716b7ab1ee2ff174cb063a73
TRAEFIK_VERSION=v3.7.10
TRAEFIK_CHART_VERSION=41.2.0
TRAEFIK_CHART_DIGEST=sha256:5d1a255b73e5dd67d70fc21b1536a405d88bf6b63896bc78dbefa15e9bfb371b
TRAEFIK_CHART_ARCHIVE_SHA256=f7f8b70f021f34164709bc6440165c0ccb79073dccb6369310d95a1c3cf8a2f0
TRAEFIK_RELEASE=traefik
TRAEFIK_NAMESPACE=platform-system
TRAEFIK_CHART=oci://ghcr.io/traefik/helm/traefik
TRAEFIK_CONFIG=$REPOSITORY_ROOT/platform/addons/traefik-gateway

require_lab_runtime() {
  require_command kind
  require_command kubectl
  require_docker
  cluster_exists || die "The exact kind cluster '$CLUSTER_NAME' does not exist."
  require_expected_context
}

short_revision() {
  git -C "$REPOSITORY_ROOT" rev-parse --short=12 HEAD
}

full_revision() {
  git -C "$REPOSITORY_ROOT" rev-parse HEAD
}

require_clean_build_sources() {
  if ! git -C "$REPOSITORY_ROOT" diff --quiet -- applications/golden-path-api charts/golden-path-api ||
     ! git -C "$REPOSITORY_ROOT" diff --cached --quiet -- applications/golden-path-api charts/golden-path-api ||
     [ -n "$(git -C "$REPOSITORY_ROOT" ls-files --others --exclude-standard -- applications/golden-path-api charts/golden-path-api)" ]; then
    die 'Application or chart sources are uncommitted. Commit reviewed sources before creating a revision-labelled image.'
  fi
}

image_tag() {
  printf '%s-%s\n' "$APP_VERSION" "$(short_revision)"
}

image_ref() {
  printf '%s:%s\n' "$APP_NAME" "$(image_tag)"
}

require_app_release() {
  helm --kube-context "$EXPECTED_CONTEXT" status "$APP_RELEASE" --namespace "$APP_NAMESPACE" >/dev/null 2>&1 ||
    die "Helm release '$APP_RELEASE' is not installed in '$APP_NAMESPACE'."
}

confirm_exact() {
  expected=$1
  message=$2
  [ -t 0 ] || die 'This operation requires an interactive terminal and explicit confirmation.'
  printf '%s\nType %s to continue: ' "$message" "$expected"
  read -r confirmation
  [ "$confirmation" = "$expected" ] || die 'Confirmation did not match; no change was made.'
}
