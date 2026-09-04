#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"

KPR_NAMESPACE=kube-system
KPR_DAEMONSET=kindnet
KPR_IMAGE=docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88
KPR_TIMEOUT_SECONDS=120
kpr_run_id="$(date +%s)-$$"
kpr_root=$REPOSITORY_ROOT/.artifacts/kindnet-policy-recovery/$kpr_run_id
kpr_raw=$(mktemp -d)
trap 'rm -rf "$kpr_raw"' EXIT HUP INT TERM

require_command kubectl
require_expected_context
mkdir -p "$kpr_root/before" "$kpr_root/after" "$kpr_root/cleanup"

kubectl_lab get daemonset "$KPR_DAEMONSET" -n "$KPR_NAMESPACE" -o json >"$kpr_raw/daemonset.json"
kubectl_lab get pods -n "$KPR_NAMESPACE" -l k8s-app=kindnet -o json >"$kpr_raw/pods.json"
kubectl_lab logs -n "$KPR_NAMESPACE" -l k8s-app=kindnet --all-containers --since=15m >"$kpr_raw/kindnet.log" 2>&1 || true
python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" preflight \
  --daemonset "$kpr_raw/daemonset.json" --pods "$kpr_raw/pods.json" --image "$KPR_IMAGE" \
  --output "$kpr_raw/identity.json"
python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/daemonset.json" "$kpr_root/before/daemonset.json"
python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/pods.json" "$kpr_root/before/pods.json"
python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/identity.json" "$kpr_root/before/identity.json"
python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/kindnet.log" "$kpr_root/before/kindnet.log"

kpr_confirmation=$(python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" confirmation --identity "$kpr_raw/identity.json" --context "$EXPECTED_CONTEXT")
confirm_exact "$kpr_confirmation" 'Restart exactly one verified kindnet Pod at a time; Docker containers and nodes are untouched.'

python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" plan --identity "$kpr_raw/identity.json" | while IFS='|' read -r kpr_node kpr_name kpr_uid; do
  kubectl_lab get daemonset "$KPR_DAEMONSET" -n "$KPR_NAMESPACE" -o json >"$kpr_raw/daemonset-current.json"
  kubectl_lab get pod "$kpr_name" -n "$KPR_NAMESPACE" -o json >"$kpr_raw/pod-current.json"
  python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" unchanged --identity "$kpr_raw/identity.json" \
    --daemonset "$kpr_raw/daemonset-current.json" --pod "$kpr_raw/pod-current.json" --node "$kpr_node" --uid "$kpr_uid"
  mkdir -p "$kpr_root/before/$kpr_name"
  kubectl_lab logs "$kpr_name" -n "$KPR_NAMESPACE" >"$kpr_raw/$kpr_name.log" 2>&1 || true
  kubectl_lab describe pod "$kpr_name" -n "$KPR_NAMESPACE" >"$kpr_raw/$kpr_name.describe" 2>&1
  kubectl_lab get events -n "$KPR_NAMESPACE" --field-selector "involvedObject.uid=$kpr_uid" -o json >"$kpr_raw/$kpr_name.events.json"
  for kpr_item in pod-current.json "$kpr_name.log" "$kpr_name.describe" "$kpr_name.events.json"; do
    python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/$kpr_item" "$kpr_root/before/$kpr_name/$kpr_item"
  done
  python3 "$SCRIPT_DIR/cleanup-kubernetes-resource.py" cleanup --context "$EXPECTED_CONTEXT" \
    --kind pod --namespace "$KPR_NAMESPACE" --name "$kpr_name" --uid "$kpr_uid" \
    --timeout-seconds "$KPR_TIMEOUT_SECONDS" --output "$kpr_root/cleanup/pod-$kpr_name.json"
  kubectl_lab wait -n "$KPR_NAMESPACE" --for=condition=Ready pod -l k8s-app=kindnet \
    --field-selector "spec.nodeName=$kpr_node" --timeout="${KPR_TIMEOUT_SECONDS}s"
  kubectl_lab get pods -n "$KPR_NAMESPACE" -l k8s-app=kindnet --field-selector "spec.nodeName=$kpr_node" -o json >"$kpr_raw/replacement.json"
  python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" replacement --pods "$kpr_raw/replacement.json" \
    --node "$kpr_node" --old-name "$kpr_name" --old-uid "$kpr_uid" --image "$KPR_IMAGE"
done

kubectl_lab get daemonset "$KPR_DAEMONSET" -n "$KPR_NAMESPACE" -o json >"$kpr_raw/daemonset-after.json"
kubectl_lab get pods -n "$KPR_NAMESPACE" -l k8s-app=kindnet -o json >"$kpr_raw/pods-after.json"
kubectl_lab logs -n "$KPR_NAMESPACE" -l k8s-app=kindnet --all-containers --since=15m >"$kpr_raw/kindnet-after.log" 2>&1 || true
python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/daemonset-after.json" "$kpr_root/after/daemonset.json"
python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/pods-after.json" "$kpr_root/after/pods.json"
python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$kpr_raw/kindnet-after.log" "$kpr_root/after/kindnet.log"
"$SCRIPT_DIR/test-kindnet-policy.sh"
python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" manifest --root "$kpr_root"
printf 'PASS  guarded sequential kindnet policy recovery completed. Evidence: %s\n' "$kpr_root"
