#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"

install_gateway() {
  require_command curl
  require_command helm
  require_command sha256sum
  require_lab_runtime
  if kubectl_lab get gatewayclass platform-traefik >/dev/null 2>&1; then
    owner=$(kubectl_lab get gatewayclass platform-traefik -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}')
    [ "$owner" = platform-engineering-lab ] || die "GatewayClass 'platform-traefik' exists but is not owned by this lab."
  fi
  if kubectl_lab get gateway platform-gateway --namespace "$TRAEFIK_NAMESPACE" >/dev/null 2>&1; then
    owner=$(kubectl_lab get gateway platform-gateway --namespace "$TRAEFIK_NAMESPACE" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}')
    [ "$owner" = platform-engineering-lab ] || die "Gateway '$TRAEFIK_NAMESPACE/platform-gateway' exists but is not owned by this lab."
  fi
  temporary_directory=$(mktemp -d)
  cleanup() { rm -rf "$temporary_directory"; }
  trap cleanup EXIT HUP INT TERM
  printf "Installing Gateway API Standard CRDs %s, then Traefik chart %s with Proxy %s.\n" "$GATEWAY_API_VERSION" "$TRAEFIK_CHART_VERSION" "$TRAEFIK_VERSION"
  pull_output=$(helm pull "$TRAEFIK_CHART" --version "$TRAEFIK_CHART_VERSION" --destination "$temporary_directory" 2>&1)
  printf '%s\n' "$pull_output"
  printf '%s\n' "$pull_output" | grep -F "Digest: $TRAEFIK_CHART_DIGEST" >/dev/null || die 'Traefik chart OCI digest does not match the approved value.'
  chart_archive=$temporary_directory/traefik-$TRAEFIK_CHART_VERSION.tgz
  printf '%s  %s\n' "$TRAEFIK_CHART_ARCHIVE_SHA256" "$chart_archive" | sha256sum --check --status || die 'Traefik chart archive checksum does not match the approved value.'
  helm template "$TRAEFIK_RELEASE" "$chart_archive" \
    --namespace "$TRAEFIK_NAMESPACE" \
    --values "$TRAEFIK_CONFIG/values.yaml" \
    --skip-crds >"$temporary_directory/traefik-rendered.yaml"
  if grep -Eq '^[[:space:]]+hostNetwork:[[:space:]]+true([[:space:]]|$)|^[[:space:]]+hostPort:[[:space:]]+[1-9][0-9]*([[:space:]]|$)' "$temporary_directory/traefik-rendered.yaml"; then
    die 'Rendered Traefik workload uses forbidden host networking or a non-zero host port.'
  fi
  curl --fail --location --silent --show-error "$GATEWAY_API_URL" --output "$temporary_directory/standard-install.yaml"
  printf '%s  %s\n' "$GATEWAY_API_SHA256" "$temporary_directory/standard-install.yaml" | sha256sum --check --status || die 'Gateway API CRD checksum does not match the approved value.'
  kubectl_lab apply --server-side --filename "$temporary_directory/standard-install.yaml"
  kubectl_lab apply --filename "$TRAEFIK_CONFIG/network-policies.yaml"
  helm upgrade --install "$TRAEFIK_RELEASE" "$chart_archive" \
    --kube-context "$EXPECTED_CONTEXT" \
    --namespace "$TRAEFIK_NAMESPACE" \
    --values "$TRAEFIK_CONFIG/values.yaml" \
    --skip-crds \
    --atomic --wait --timeout 180s
  kubectl_lab apply --filename "$TRAEFIK_CONFIG/gateway.yaml"
}

status_gateway() {
  require_command helm
  require_lab_runtime
  helm --kube-context "$EXPECTED_CONTEXT" status "$TRAEFIK_RELEASE" --namespace "$TRAEFIK_NAMESPACE"
  kubectl_lab get gatewayclass,gateway --all-namespaces
  kubectl_lab get deployment,pods,service --namespace "$TRAEFIK_NAMESPACE" -l app.kubernetes.io/name=traefik -o wide
}

validate_gateway() {
  require_command helm
  require_lab_runtime
  helm --kube-context "$EXPECTED_CONTEXT" status "$TRAEFIK_RELEASE" --namespace "$TRAEFIK_NAMESPACE" >/dev/null
  kubectl_lab rollout status deployment/traefik --namespace "$TRAEFIK_NAMESPACE" --timeout=60s
  kubectl_lab wait --for=condition=Accepted gatewayclass/platform-traefik --timeout=60s
  kubectl_lab wait --namespace "$TRAEFIK_NAMESPACE" --for=condition=Programmed gateway/platform-gateway --timeout=60s
  image=$(kubectl_lab get deployment traefik --namespace "$TRAEFIK_NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}')
  case "$image" in *"$TRAEFIK_VERSION"*) ;; *) die "Traefik image '$image' does not match $TRAEFIK_VERSION." ;; esac
  http_node_port=$(kubectl_lab get service traefik --namespace "$TRAEFIK_NAMESPACE" -o jsonpath='{.spec.ports[?(@.name=="web")].nodePort}')
  https_node_port=$(kubectl_lab get service traefik --namespace "$TRAEFIK_NAMESPACE" -o jsonpath='{.spec.ports[?(@.name=="websecure")].nodePort}')
  [ "$http_node_port" = 30080 ] || die "Traefik HTTP NodePort is '${http_node_port:-unset}', expected 30080."
  [ "$https_node_port" = 30443 ] || die "Traefik HTTPS NodePort is '${https_node_port:-unset}', expected 30443."
  http_binding=$(docker port "$CONTROL_PLANE_CONTAINER" 30080/tcp 2>/dev/null || true)
  https_binding=$(docker port "$CONTROL_PLANE_CONTAINER" 30443/tcp 2>/dev/null || true)
  [ "$http_binding" = 127.0.0.1:80 ] || die "Control-plane port 30080 maps to '${http_binding:-nothing}', expected 127.0.0.1:80."
  [ "$https_binding" = 127.0.0.1:443 ] || die "Control-plane port 30443 maps to '${https_binding:-nothing}', expected 127.0.0.1:443."
  host_network=$(kubectl_lab get deployment traefik --namespace "$TRAEFIK_NAMESPACE" -o jsonpath='{.spec.template.spec.hostNetwork}')
  [ "$host_network" != true ] || die 'Traefik must not use host networking.'
  host_ports=$(kubectl_lab get deployment traefik --namespace "$TRAEFIK_NAMESPACE" -o jsonpath='{range .spec.template.spec.containers[*].ports[*]}{.hostPort}{"\n"}{end}')
  if printf '%s\n' "$host_ports" | awk 'NF && $0 != "0" {found=1} END {exit found ? 0 : 1}'; then
    die 'Traefik must not declare a non-zero hostPort.'
  fi
  printf '%s\n' 'Gateway validation passed.'
}

uninstall_gateway() {
  require_command helm
  require_lab_runtime
  helm --kube-context "$EXPECTED_CONTEXT" status "$TRAEFIK_RELEASE" --namespace "$TRAEFIK_NAMESPACE" >/dev/null 2>&1 || die "Traefik release '$TRAEFIK_RELEASE' is not installed."
  gateway_class_owner=$(kubectl_lab get gatewayclass platform-traefik -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>/dev/null || true)
  [ -z "$gateway_class_owner" ] || [ "$gateway_class_owner" = platform-engineering-lab ] || die "GatewayClass 'platform-traefik' is not owned by this lab."
  gateway_owner=$(kubectl_lab get gateway platform-gateway --namespace "$TRAEFIK_NAMESPACE" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>/dev/null || true)
  [ -z "$gateway_owner" ] || [ "$gateway_owner" = platform-engineering-lab ] || die "Gateway '$TRAEFIK_NAMESPACE/platform-gateway' is not owned by this lab."
  confirm_exact "$TRAEFIK_RELEASE" "This removes the platform Gateway and Traefik release. Shared Gateway API CRDs are preserved."
  kubectl_lab delete --filename "$TRAEFIK_CONFIG/gateway.yaml" --ignore-not-found
  helm uninstall "$TRAEFIK_RELEASE" --kube-context "$EXPECTED_CONTEXT" --namespace "$TRAEFIK_NAMESPACE" --wait
  kubectl_lab delete --filename "$TRAEFIK_CONFIG/network-policies.yaml" --ignore-not-found
}

usage() {
  printf 'usage: %s {install|status|validate|uninstall}\n' "$0" >&2
  exit 2
}

case ${1:-} in
  install) install_gateway ;;
  status) status_gateway ;;
  validate) validate_gateway ;;
  uninstall) uninstall_gateway ;;
  *) usage ;;
esac
