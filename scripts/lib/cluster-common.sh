#!/bin/sh

# This file exports constants and helpers to multiple scripts.
# shellcheck disable=SC2034

CLUSTER_NAME=platform-engineering-lab
EXPECTED_CONTEXT=kind-platform-engineering-lab
KUBERNETES_VERSION=v1.35.0
KIND_VERSION=v0.31.0
CONTROL_PLANE_CONTAINER=platform-engineering-lab-control-plane

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH='' cd "$SCRIPT_DIR/.." && pwd)
CLUSTER_CONFIG=$REPOSITORY_ROOT/platform/bootstrap/kind/cluster.yaml
BASELINE_DIR=$REPOSITORY_ROOT/platform/baseline

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required. Install it using the official documentation, then retry."
}

require_docker() {
  require_command docker
  docker info >/dev/null 2>&1 || die 'Docker is not reachable. Start the intended local Docker runtime and verify it with: docker info'
}

cluster_exists() {
  kind get clusters 2>/dev/null | grep -Fx "$CLUSTER_NAME" >/dev/null 2>&1
}

context_exists() {
  kubectl config get-contexts -o name 2>/dev/null | grep -Fx "$EXPECTED_CONTEXT" >/dev/null 2>&1
}

require_expected_context() {
  current_context=$(kubectl config current-context 2>/dev/null || true)
  [ "$current_context" = "$EXPECTED_CONTEXT" ] || die "Active context is '$current_context'; expected '$EXPECTED_CONTEXT'. Refusing to continue. Select it explicitly with: kubectl config use-context $EXPECTED_CONTEXT"
}

kubectl_lab() {
  kubectl --context "$EXPECTED_CONTEXT" "$@"
}

show_cluster_inventory() {
  printf '%s\n' 'Workloads currently visible in the lab cluster:'
  kubectl_lab get deployments,replicasets,statefulsets,daemonsets,jobs,cronjobs,pods --all-namespaces -o wide ||
    die 'Unable to inventory workloads; refusing to delete the cluster.'
  printf '\n%s\n' 'Persistent storage currently visible in the lab cluster:'
  kubectl_lab get persistentvolumes,persistentvolumeclaims --all-namespaces ||
    die 'Unable to inventory persistent storage; refusing to delete the cluster.'
}

confirm_cluster_destruction() {
  [ -t 0 ] || die 'Destruction requires an interactive terminal and explicit confirmation.'
  show_cluster_inventory
  printf '\nDeleting %s permanently removes its namespaces, workloads, Services, configuration, Secrets, RBAC, CRDs, and local persistent-volume data.\n' "$CLUSTER_NAME"
  printf 'Type the exact cluster name to continue: '
  read -r confirmation
  [ "$confirmation" = "$CLUSTER_NAME" ] || die 'Confirmation did not match; no cluster was deleted.'
}
