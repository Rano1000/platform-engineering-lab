#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"

PASS_COUNT=0
FAIL_COUNT=0
RUNTIME_CHECK_TIMEOUT=30s

pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS  %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL  %s\n' "$*"; }

require_command kubectl
require_command docker
require_expected_context

if kubectl_lab get --raw=/readyz >/dev/null 2>&1; then
  pass 'Kubernetes API is reachable and ready.'
else
  die "Kubernetes API for '$EXPECTED_CONTEXT' is not ready."
fi

if kubectl_lab diff --kustomize "$BASELINE_DIR" >/dev/null 2>&1; then
  pass 'live baseline matches the repository declarations.'
else
  fail 'live baseline differs from the repository or could not be compared.'
fi

if node_table=$(kubectl_lab get nodes --no-headers 2>/dev/null); then
  node_count=$(printf '%s\n' "$node_table" | awk 'NF {count++} END {print count + 0}')
else
  die 'Unable to retrieve nodes from the expected cluster.'
fi
if [ "$node_count" -eq 3 ]; then pass 'exactly three nodes exist.'; else fail "expected three nodes; found $node_count."; fi

control_planes=$(kubectl_lab get nodes -l node-role.kubernetes.io/control-plane --no-headers 2>/dev/null | wc -l | tr -d ' ')
workers=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [ "$control_planes" -eq 1 ] && [ "$workers" -eq 2 ]; then pass 'topology is one control plane and two workers.'; else fail "unexpected roles: control-planes=$control_planes workers=$workers."; fi

ingress_ready=$(kubectl_lab get nodes -l node-role.kubernetes.io/control-plane -o jsonpath='{.items[0].metadata.labels.ingress-ready}' 2>/dev/null || true)
if [ "$ingress_ready" = true ]; then pass 'control-plane node is labeled ingress-ready=true.'; else fail 'control-plane node is missing ingress-ready=true.'; fi

not_ready=$(printf '%s\n' "$node_table" | awk '$2 != "Ready" {count++} END {print count + 0}')
if [ "$not_ready" -eq 0 ]; then pass 'all nodes are Ready.'; else fail "$not_ready node(s) are not Ready."; fi

if node_versions=$(kubectl_lab get nodes -o jsonpath='{range .items[*]}{.status.nodeInfo.kubeletVersion}{"\n"}{end}' 2>/dev/null); then
  wrong_versions=$(printf '%s\n' "$node_versions" | awk -v expected="$KUBERNETES_VERSION" 'NF && $0 != expected {count++} END {print count + 0}')
else
  die 'Unable to retrieve Kubernetes node versions.'
fi
if [ "$wrong_versions" -eq 0 ]; then pass "all nodes run Kubernetes $KUBERNETES_VERSION."; else fail "$wrong_versions node(s) do not run $KUBERNETES_VERSION."; fi

if kubectl_lab rollout status deployment/coredns --namespace kube-system --timeout="$RUNTIME_CHECK_TIMEOUT" >/dev/null 2>&1; then pass 'CoreDNS is available.'; else fail 'CoreDNS is not available.'; fi
if kubectl_lab rollout status daemonset/kindnet --namespace kube-system --timeout="$RUNTIME_CHECK_TIMEOUT" >/dev/null 2>&1; then pass 'kindnet CNI is available.'; else fail 'kindnet CNI is not available.'; fi
if kubectl_lab rollout status daemonset/kube-proxy --namespace kube-system --timeout="$RUNTIME_CHECK_TIMEOUT" >/dev/null 2>&1; then pass 'kube-proxy is available.'; else fail 'kube-proxy is not available.'; fi
if kubectl_lab wait --namespace kube-system --for=condition=Ready pods --all --timeout="$RUNTIME_CHECK_TIMEOUT" >/dev/null 2>&1; then pass 'all critical system Pods are Ready.'; else fail 'one or more critical system Pods are not Ready.'; fi

for namespace in platform-system platform-apps observability security gitops; do
  if kubectl_lab get namespace "$namespace" >/dev/null 2>&1; then
    owner=$(kubectl_lab get namespace "$namespace" -o jsonpath='{.metadata.labels.platform\.engineering-lab/owner}')
    managed_by=$(kubectl_lab get namespace "$namespace" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}')
    enforce=$(kubectl_lab get namespace "$namespace" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}')
    enforce_version=$(kubectl_lab get namespace "$namespace" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce-version}')
    expected_enforce=baseline
    if [ "$namespace" = platform-apps ]; then
      expected_enforce=restricted
    fi
    if [ "$owner" = platform-team ] && [ "$managed_by" = platform-engineering-lab ] && [ "$enforce" = "$expected_enforce" ] && [ "$enforce_version" = v1.35 ]; then
      pass "namespace $namespace has ownership and Pod Security labels."
    else
      fail "namespace $namespace has incomplete baseline labels."
    fi
  else
    fail "namespace $namespace is missing."
  fi
done

if kubectl_lab get limitrange application-defaults --namespace platform-apps >/dev/null 2>&1; then pass 'application LimitRange exists.'; else fail 'application LimitRange is missing.'; fi
if kubectl_lab get resourcequota application-budget --namespace platform-apps >/dev/null 2>&1; then pass 'application ResourceQuota exists.'; else fail 'application ResourceQuota is missing.'; fi

quota_pods=$(kubectl_lab get resourcequota application-budget --namespace platform-apps -o jsonpath='{.spec.hard.pods}' 2>/dev/null || true)
quota_storage=$(kubectl_lab get resourcequota application-budget --namespace platform-apps -o jsonpath='{.spec.hard.requests\.storage}' 2>/dev/null || true)
limit_memory=$(kubectl_lab get limitrange application-defaults --namespace platform-apps -o jsonpath='{.spec.limits[0].default.memory}' 2>/dev/null || true)
if [ "$quota_pods" = 15 ] && [ "$quota_storage" = 20Gi ] && [ "$limit_memory" = 512Mi ]; then pass 'application resource controls match the local budget.'; else fail 'application resource controls differ from the approved local budget.'; fi

for namespace in platform-system platform-apps observability security gitops; do
  for policy in default-deny allow-dns-egress; do
    if kubectl_lab get networkpolicy "$policy" --namespace "$namespace" >/dev/null 2>&1; then pass "$namespace/$policy exists."; else fail "$namespace/$policy is missing."; fi
  done
done

default_classes=$(kubectl_lab get storageclass -o go-template='{{range .items}}{{if .metadata.annotations}}{{if eq (index .metadata.annotations "storageclass.kubernetes.io/is-default-class") "true"}}{{.metadata.name}}{{"\n"}}{{end}}{{end}}{{end}}')
default_count=$(printf '%s\n' "$default_classes" | awk 'NF {count++} END {print count + 0}')
if [ "$default_count" -eq 1 ]; then
  provisioner=$(kubectl_lab get storageclass "$default_classes" -o jsonpath='{.provisioner}')
  if [ -n "$provisioner" ]; then pass "one default StorageClass exists: $default_classes ($provisioner)."; else fail 'default StorageClass has no provisioner.'; fi
else
  fail "expected one default StorageClass; found $default_count."
fi

if docker inspect "$CONTROL_PLANE_CONTAINER" >/dev/null 2>&1; then
  http_binding=$(docker port "$CONTROL_PLANE_CONTAINER" 30080/tcp 2>/dev/null || true)
  https_binding=$(docker port "$CONTROL_PLANE_CONTAINER" 30443/tcp 2>/dev/null || true)
  if [ "$http_binding" = '127.0.0.1:80' ]; then
    pass 'HTTP maps from 127.0.0.1:80 to control-plane container port 30080.'
  else
    fail "unexpected HTTP binding: ${http_binding:-none}."
  fi
  if [ "$https_binding" = '127.0.0.1:443' ]; then
    pass 'HTTPS maps from 127.0.0.1:443 to control-plane container port 30443.'
  else
    fail "unexpected HTTPS binding: ${https_binding:-none}."
  fi
else
  fail "control-plane container '$CONTROL_PLANE_CONTAINER' is not visible to Docker."
fi

printf '\nSummary: %s PASS, %s FAIL\n' "$PASS_COUNT" "$FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ]
