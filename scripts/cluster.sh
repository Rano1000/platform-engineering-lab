#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=scripts/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"

check_kind_version() {
  installed=$(kind version 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^v[0-9]+\.[0-9]+\.[0-9]+/) {sub(/-.*/, "", $i); print $i; exit}}')
  [ "$installed" = "$KIND_VERSION" ] || die "kind $KIND_VERSION is required; found '${installed:-unknown}'. Use the pinned stable release documented in docs/reference/tooling.md."
}

check_ports() {
  for port in 80 443; do
    if docker ps --format '{{.Ports}}' | grep -E "(^|, )[^,]*:$port->" >/dev/null 2>&1; then
      die "Host port $port is already published by a Docker container. Stop the intended owner or change the approved design."
    fi
    if command -v ss >/dev/null 2>&1 && ss -H -ltn "sport = :$port" 2>/dev/null | grep . >/dev/null 2>&1; then
      die "Host port $port is already in use. Identify its owner before creating the cluster."
    fi
  done
}

wait_for_cluster() {
  printf '%s\n' 'Waiting for all three Kubernetes nodes to become Ready...'
  kubectl_lab wait --for=condition=Ready nodes --all --timeout=180s
  printf '%s\n' 'Waiting for critical kube-system Pods to become Ready...'
  kubectl_lab wait --namespace kube-system --for=condition=Ready pods --all --timeout=180s
}

apply_namespaces() {
  require_command kubectl
  require_expected_context
  kubectl_lab apply --filename "$BASELINE_DIR/namespaces.yaml"
}

apply_policies() {
  require_command kubectl
  require_expected_context
  kubectl_lab apply --filename "$BASELINE_DIR/resource-controls.yaml"
  kubectl_lab apply --filename "$BASELINE_DIR/network-policies.yaml"
}

create_cluster() {
  require_command kind
  require_command kubectl
  require_docker
  check_kind_version

  if cluster_exists; then
    printf "Cluster '%s' already exists; no replacement was attempted. Run 'make cluster-validate' to inspect it.\n" "$CLUSTER_NAME"
    return 0
  fi
  if context_exists; then
    die "Context '$EXPECTED_CONTEXT' already exists without a discoverable matching kind cluster. Refusing to overwrite it. Inspect Docker and kubeconfig manually."
  fi

  check_ports
  printf "Creating kind cluster '%s' from %s...\n" "$CLUSTER_NAME" "$CLUSTER_CONFIG"
  kind create cluster --name "$CLUSTER_NAME" --config "$CLUSTER_CONFIG" --wait 180s
  require_expected_context
  wait_for_cluster
  apply_namespaces
  apply_policies
  "$SCRIPT_DIR/validate-cluster.sh"
}

show_status() {
  require_command kubectl
  require_expected_context
  kubectl_lab cluster-info
  kubectl_lab get nodes -o wide
  kubectl_lab get pods --namespace kube-system -o wide
  kubectl_lab get namespaces
}

destroy_cluster() {
  require_command kind
  require_command kubectl
  require_docker
  cluster_exists || die "The exact kind cluster '$CLUSTER_NAME' does not exist; nothing was deleted."
  require_expected_context
  confirm_cluster_destruction
  kind delete cluster --name "$CLUSTER_NAME"
}

recreate_cluster() {
  require_command kind
  require_command kubectl
  require_docker
  cluster_exists || die "The exact kind cluster '$CLUSTER_NAME' does not exist. Use 'make cluster-create' instead."
  require_expected_context
  confirm_cluster_destruction
  kind delete cluster --name "$CLUSTER_NAME"
  create_cluster
}

usage() {
  printf 'usage: %s {create|status|validate|destroy|recreate|namespaces-apply|policies-apply}\n' "$0" >&2
  exit 2
}

case ${1:-} in
  create) create_cluster ;;
  status) show_status ;;
  validate) "$SCRIPT_DIR/validate-cluster.sh" ;;
  destroy) destroy_cluster ;;
  recreate) recreate_cluster ;;
  namespaces-apply) apply_namespaces ;;
  policies-apply) apply_policies ;;
  *) usage ;;
esac
