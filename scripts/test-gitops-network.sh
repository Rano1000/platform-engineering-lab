#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"

require_lab_runtime
require_app_release
suffix="$(date +%s)-$$"
pod="argocd-hook-network-$suffix"
cleanup() {
  kubectl_lab delete pod "$pod" --namespace gitops --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM
confirm_exact argocd-redis-secret-init-network \
  "Create one temporary restricted Pod in gitops with the Redis hook labels. It tests Kubernetes API TCP 443 and denied unrelated TCP 443, then removes itself."
image=$(kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}')
[ -n "$image" ] || die 'The deployed application image could not be resolved for the temporary client.'
command="import socket; socket.create_connection(('10.96.0.1',443),5).close();\ntry: socket.create_connection(('1.1.1.1',443),5); raise SystemExit('unrelated egress unexpectedly succeeded')\nexcept (TimeoutError,OSError): pass"
overrides=$(printf '{"spec":{"automountServiceAccountToken":false,"securityContext":{"runAsNonRoot":true,"runAsUser":10001,"runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"client","image":"%s","imagePullPolicy":"IfNotPresent","command":["python","-c"],"args":["%s"],"resources":{"requests":{"cpu":"10m","memory":"16Mi"},"limits":{"cpu":"50m","memory":"32Mi"}},"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}}]}}' "$image" "$command")
kubectl_lab run "$pod" --namespace gitops --restart=Never --image="$image" \
  --labels='app.kubernetes.io/name=argocd-redis-secret-init,app.kubernetes.io/component=redis-secret-init,app.kubernetes.io/instance=argocd' \
  --overrides="$overrides"
kubectl_lab wait --namespace gitops --for=jsonpath='{.status.phase}'=Succeeded "pod/$pod" --timeout=30s
printf '%s\n' 'GitOps hook network test passed: Kubernetes API TCP 443 succeeded and unrelated TCP 443 was denied.'
