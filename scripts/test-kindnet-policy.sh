#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"

require_expected_context
knp_root=$REPOSITORY_ROOT/.artifacts/kindnet-policy-enforcement/$(date +%s)-$$
mkdir -p "$knp_root"
knp_temporary=$(mktemp -d)
trap 'rm -rf "$knp_temporary"' EXIT HUP INT TERM

kubectl_lab get daemonset kindnet -n kube-system -o json >"$knp_temporary/daemonset.json"
kubectl_lab get pods -n kube-system -l app=kindnet -o json >"$knp_temporary/pods.json"
kubectl_lab logs -n kube-system -l app=kindnet --all-containers --since=10m >"$knp_temporary/kindnet.log" 2>&1 || true
for knp_file in daemonset.json pods.json kindnet.log; do
  python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$knp_temporary/$knp_file" "$knp_root/$knp_file"
done
python3 "$SCRIPT_DIR/validate-kindnet-enforcement.py" preflight \
  --daemonset "$knp_root/daemonset.json" --pods "$knp_root/pods.json" --logs "$knp_root/kindnet.log"

# The proven single-assertion harness supplies an exact listener, default-deny checks,
# exact API allows, unrelated denies, diagnostics, and UID-aware cleanup. Run it once
# with each worker as the source; never overlap the two transactions.
for knp_index in 0 1; do
  GITOPS_NETWORK_NONINTERACTIVE=1 GITOPS_NETWORK_WORKER_INDEX=$knp_index \
    GITOPS_NETWORK_DIAGNOSTICS="$knp_root/worker-$knp_index" "$SCRIPT_DIR/test-gitops-network.sh"
  knp_node=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' -o "jsonpath={.items[$knp_index].metadata.name}")
  knp_image=$(kubectl_lab get deployment golden-path-golden-path-api -n platform-apps -o jsonpath='{.spec.template.spec.containers[0].image}')
  knp_name="kindnet-dns-$knp_index-$(basename "$knp_root")"
  knp_override=$(printf '{"spec":{"nodeName":"%s","automountServiceAccountToken":false,"restartPolicy":"Never","securityContext":{"runAsNonRoot":true,"runAsUser":10001,"runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"dns","image":"%s","command":["python","-c","import socket,json; print(json.dumps({\"dns\":socket.getaddrinfo(\"kubernetes.default.svc\",443)[0][4][0]}))"],"resources":{"requests":{"cpu":"5m","memory":"16Mi"},"limits":{"cpu":"25m","memory":"32Mi"}},"securityContext":{"allowPrivilegeEscalation":false,"readOnlyRootFilesystem":true,"capabilities":{"drop":["ALL"]}}}]}}' "$knp_node" "$knp_image")
  kubectl_lab run "$knp_name" -n gitops --restart=Never --image="$knp_image" \
    --labels="app.kubernetes.io/part-of=argocd,app.kubernetes.io/name=argocd-repo-server" --overrides="$knp_override"
  knp_uid=$(kubectl_lab get pod "$knp_name" -n gitops -o jsonpath='{.metadata.uid}')
  kubectl_lab wait -n gitops --for=jsonpath='{.status.phase}'=Succeeded "pod/$knp_name" --timeout=30s
  kubectl_lab logs "$knp_name" -n gitops >"$knp_temporary/$knp_name.log"
  python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$knp_temporary/$knp_name.log" "$knp_root/$knp_name.json"
  python3 "$SCRIPT_DIR/cleanup-kubernetes-resource.py" cleanup --context "$EXPECTED_CONTEXT" --kind pod \
    --namespace gitops --name "$knp_name" --uid "$knp_uid" --timeout-seconds 30 \
    --output "$knp_root/$knp_name-cleanup.json"
done
python3 "$SCRIPT_DIR/validate-kindnet-enforcement.py" evidence --root "$knp_root"
printf 'PASS  functional NetworkPolicy enforcement passed independently on both workers. Evidence: %s\n' "$knp_root"
