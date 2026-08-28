#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"
# shellcheck source=SCRIPTDIR/lib/gitops-common.sh
. "$SCRIPT_DIR/lib/gitops-common.sh"

require_lab_runtime
require_app_release
temporary=$(mktemp -d)
suffix="$(date +%s)-$$"
listener="argocd-api-negative-$suffix"
listener_policy=$listener
created_pods=''
cleanup() {
  for resource in $created_pods; do
    kubectl_lab delete pod "$resource" --namespace "$ARGOCD_NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  done
  kubectl_lab delete networkpolicy "$listener_policy" --namespace "$ARGOCD_NAMESPACE" --ignore-not-found >/dev/null 2>&1 || true
  kubectl_lab delete pod "$listener" --namespace "$ARGOCD_NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM

if [ -n "${GITOPS_NETWORK_IDENTITY:-}" ]; then
  identity=$GITOPS_NETWORK_IDENTITY
else
  resolve_argocd_api_endpoint "$temporary" network-test >/dev/null
  identity=$temporary/network-test-identity.json
fi
verify_live_argocd_api_policies "$identity" "$temporary/live-policies.json"

if [ "${GITOPS_NETWORK_NONINTERACTIVE:-0}" != 1 ]; then
  confirm_exact argocd-api-endpoint-network \
    "Create worker-pinned temporary Pods in gitops. Approved Argo API identities may reach only the verified API endpoint; repository-server, Redis, and unlabelled identities may not. A cleanup trap removes every temporary Pod."
fi

python3 - "$identity" >"$temporary/endpoint.txt" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
print(value["apiEndpoint"]["address"])
print(value["apiEndpoint"]["port"])
PY
api_ip=$(sed -n '1p' "$temporary/endpoint.txt")
api_port=$(sed -n '2p' "$temporary/endpoint.txt")
worker=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[0].metadata.name}')
[ -n "$worker" ] || die 'No worker node is available for the network preflight.'
other_worker=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[1].metadata.name}')
[ -n "$other_worker" ] || die 'A second worker is required for the negative listener.'
image=$(kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}')
[ -n "$image" ] || die 'The deployed immutable application image could not be resolved.'

listener_overrides=$(printf '{"spec":{"nodeName":"%s","automountServiceAccountToken":false,"securityContext":{"runAsNonRoot":true,"runAsUser":10001,"runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"listener","image":"%s","imagePullPolicy":"IfNotPresent","command":["python","-c"],"args":["import socket; s=socket.socket(); s.bind((\u00270.0.0.0\u0027,6443)); s.listen(); s.accept()"],"ports":[{"containerPort":6443}],"resources":{"requests":{"cpu":"5m","memory":"16Mi"},"limits":{"cpu":"25m","memory":"32Mi"}},"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}}]}}' "$other_worker" "$image")
kubectl_lab run "$listener" --namespace "$ARGOCD_NAMESPACE" --restart=Never --image="$image" \
  --labels="platform.engineering-lab/network-test-listener=$suffix" --overrides="$listener_overrides"
kubectl_lab wait --namespace "$ARGOCD_NAMESPACE" --for=condition=Ready "pod/$listener" --timeout=30s
listener_ip=$(kubectl_lab get pod "$listener" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.status.podIP}')
[ -n "$listener_ip" ] || die 'Temporary negative listener has no Pod IP.'
cat >"$temporary/listener-policy.yaml" <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: $listener_policy
  namespace: $ARGOCD_NAMESPACE
spec:
  podSelector:
    matchLabels:
      platform.engineering-lab/network-test-listener: $suffix
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: $ARGOCD_NAMESPACE
      ports:
        - {protocol: TCP, port: 6443}
EOF
kubectl_lab apply -f "$temporary/listener-policy.yaml"

run_case() {
  name=$1 labels=$2 expected=$3
  pod="$name-$suffix"
  created_pods="$created_pods $pod"
  if [ "$expected" = allow ]; then
    code="import socket; socket.create_connection(('$api_ip',$api_port),5).close();\nfor h,p in [('1.1.1.1',443),('$listener_ip',6443)]:\n try: socket.create_connection((h,p),2); raise SystemExit('unrelated egress unexpectedly succeeded')\n except (TimeoutError,OSError): pass"
  else
    code="import socket\ntry: socket.create_connection(('$api_ip',$api_port),2); raise SystemExit('API egress unexpectedly succeeded')\nexcept (TimeoutError,OSError): pass"
  fi
  overrides=$(printf '{"spec":{"nodeName":"%s","automountServiceAccountToken":false,"securityContext":{"runAsNonRoot":true,"runAsUser":10001,"runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"client","image":"%s","imagePullPolicy":"IfNotPresent","command":["python","-c"],"args":["%s"],"resources":{"requests":{"cpu":"5m","memory":"16Mi"},"limits":{"cpu":"25m","memory":"32Mi"}},"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}}]}}' "$worker" "$image" "$code")
  kubectl_lab run "$pod" --namespace "$ARGOCD_NAMESPACE" --restart=Never --image="$image" --labels="$labels" --overrides="$overrides"
  kubectl_lab wait --namespace "$ARGOCD_NAMESPACE" --for=jsonpath='{.status.phase}'=Succeeded "pod/$pod" --timeout=30s
}

run_case argocd-hook-allow 'app.kubernetes.io/name=argocd-redis-secret-init,app.kubernetes.io/component=redis-secret-init,app.kubernetes.io/instance=argocd' allow
run_case argocd-controller-allow 'app.kubernetes.io/name=argocd-application-controller,app.kubernetes.io/component=application-controller,app.kubernetes.io/instance=argocd' allow
run_case argocd-server-allow 'app.kubernetes.io/name=argocd-server,app.kubernetes.io/component=server,app.kubernetes.io/instance=argocd' allow
run_case argocd-repo-deny 'app.kubernetes.io/name=argocd-repo-server,app.kubernetes.io/component=repo-server,app.kubernetes.io/instance=argocd' deny
run_case argocd-redis-deny 'app.kubernetes.io/name=argocd-redis,app.kubernetes.io/component=redis,app.kubernetes.io/instance=argocd' deny
run_case argocd-unlabelled-deny "platform.engineering-lab/network-test=$suffix" deny
printf '%s\n' "GitOps network preflight passed on worker '$worker': exact API access is limited to three approved identities; unrelated TCP 443/6443 and other identities are denied."
