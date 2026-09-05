#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/diagnostic-common.sh
. "$SCRIPT_DIR/lib/diagnostic-common.sh"

require_expected_context
knp_global_artifact_base=$REPOSITORY_ROOT/.artifacts
knp_artifact_base=${KINDNET_POLICY_ARTIFACT_BASE:-$knp_global_artifact_base/kindnet-policy-enforcement}
knp_root=${KINDNET_POLICY_EVIDENCE_ROOT:-$knp_artifact_base/$(date +%s)-$$}
python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir --base "$knp_global_artifact_base" --root "$knp_artifact_base" --path "$knp_root"
knp_temporary=$(mktemp -d)
trap 'rm -rf "$knp_temporary"' EXIT HUP INT TERM

kubectl_lab get daemonset kindnet -n kube-system -o json >"$knp_temporary/daemonset.json"
kubectl_lab get pods -n kube-system -l app=kindnet -o json >"$knp_temporary/pods.json"
kubectl_lab logs -n kube-system -l app=kindnet --all-containers --since=10m >"$knp_temporary/kindnet.log" 2>&1 || true
python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" preflight \
  --daemonset "$knp_temporary/daemonset.json" --pods "$knp_temporary/pods.json" \
  --image docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88 \
  --output "$knp_temporary/identity.json"
for knp_file in daemonset.json pods.json kindnet.log identity.json; do
  python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$knp_temporary/$knp_file" "$knp_root/$knp_file"
done
python3 "$SCRIPT_DIR/validate-kindnet-enforcement.py" preflight \
  --daemonset "$knp_root/daemonset.json" --pods "$knp_root/pods.json" --logs "$knp_root/kindnet.log"

if [ "${KINDNET_POLICY_REQUIRE_CONFIRMATION:-0}" = 1 ]; then
  knp_confirmation=$(python3 "$SCRIPT_DIR/validate-kindnet-recovery.py" confirmation \
    --identity "$knp_root/identity.json" --context "$EXPECTED_CONTEXT")
  knp_confirmation="kindnet-policy-validation/$knp_confirmation"
  printf 'Required confirmation: %s\n' "$knp_confirmation"
  confirm_exact "$knp_confirmation" \
    'Create only unique temporary policy-test resources; kindnet Pods, nodes, and Docker containers are untouched.'
fi

# The proven single-assertion harness supplies an exact listener, default-deny checks,
# exact API allows, unrelated denies, diagnostics, and UID-aware cleanup. Run it once
# with each worker as the source; never overlap the two transactions.
for knp_index in 0 1; do
  GITOPS_NETWORK_NONINTERACTIVE=1 GITOPS_NETWORK_WORKER_INDEX=$knp_index \
    GITOPS_NETWORK_ARTIFACT_BASE="$knp_root" GITOPS_NETWORK_DIAGNOSTICS="$knp_root/worker-$knp_index" \
    "$SCRIPT_DIR/test-gitops-network.sh"
  knp_node=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' -o "jsonpath={.items[$knp_index].metadata.name}")
  knp_image=$(kubectl_lab get deployment golden-path-golden-path-api -n platform-apps -o jsonpath='{.spec.template.spec.containers[0].image}')
  knp_name="kindnet-dns-$knp_index-$(basename "$knp_root")"
  knp_override=$(python3 "$SCRIPT_DIR/kindnet-dns-probe.py" pod-overrides --node "$knp_node" --image "$knp_image")
  knp_created_name=$(diagnostic_artifact_name "$knp_name" created)
  kubectl_lab run "$knp_name" -n gitops --restart=Never --image="$knp_image" \
    --labels="app.kubernetes.io/part-of=argocd,app.kubernetes.io/name=argocd-repo-server" \
    --overrides="$knp_override" -o json >"$knp_temporary/$knp_created_name"
  knp_uid=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["uid"])' "$knp_temporary/$knp_created_name")
  knp_dns_elapsed=0 knp_dns_phase=''
  while [ "$knp_dns_elapsed" -lt 30 ]; do
    knp_dns_phase=$(kubectl_lab get pod "$knp_name" -n gitops -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case $knp_dns_phase in Succeeded|Failed) break ;; esac
    sleep 1; knp_dns_elapsed=$((knp_dns_elapsed + 1))
  done
  kubectl_lab logs "$knp_name" -n gitops >"$knp_temporary/$(diagnostic_artifact_name "$knp_name" log)"
  kubectl_lab get pod "$knp_name" -n gitops -o json >"$knp_temporary/$(diagnostic_artifact_name "$knp_name" pod)"
  kubectl_lab describe pod "$knp_name" -n gitops >"$knp_temporary/$(diagnostic_artifact_name "$knp_name" describe)" 2>&1
  kubectl_lab get events -n gitops --field-selector "involvedObject.uid=$knp_uid" -o json >"$knp_temporary/$(diagnostic_artifact_name "$knp_name" events)"
  for knp_dns_kind in created log pod describe events; do
    knp_dns_name=$(diagnostic_artifact_name "$knp_name" "$knp_dns_kind")
    python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$knp_temporary/$knp_dns_name" "$knp_root/$knp_dns_name"
  done
  knp_cleanup_name=$(diagnostic_artifact_name "$knp_name" cleanup)
  python3 "$SCRIPT_DIR/kindnet-dns-probe.py" validate \
    --log "$knp_root/$(diagnostic_artifact_name "$knp_name" log)" \
    --pod "$knp_root/$(diagnostic_artifact_name "$knp_name" pod)" --node "$knp_node"
  python3 "$SCRIPT_DIR/cleanup-kubernetes-resource.py" cleanup --context "$EXPECTED_CONTEXT" --kind pod \
    --namespace gitops --name "$knp_name" --uid "$knp_uid" --timeout-seconds 30 \
    --output "$knp_root/$knp_cleanup_name"
  python3 "$SCRIPT_DIR/validate-kindnet-enforcement.py" dns-manifest --root "$knp_root" \
    --name "$knp_name" --node "$knp_node" --uid "$knp_uid"
done
find "$knp_root" -type f ! -name evidence-manifest.json -print0 | \
  xargs -0 python3 "$SCRIPT_DIR/redact-network-diagnostics.py"
python3 "$SCRIPT_DIR/validate-kindnet-enforcement.py" evidence --root "$knp_root"
printf 'PASS  functional NetworkPolicy enforcement passed independently on both workers. Evidence: %s\n' "$knp_root"
