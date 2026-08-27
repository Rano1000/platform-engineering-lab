#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"
# shellcheck source=SCRIPTDIR/lib/gitops-common.sh
. "$SCRIPT_DIR/lib/gitops-common.sh"

PASS_COUNT=0
FAIL_COUNT=0
pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS  %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL  %s\n' "$*"; }

require_lab_runtime
if helm --kube-context "$EXPECTED_CONTEXT" status "$ARGOCD_RELEASE" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then pass 'Argo CD Helm release exists.'; else fail 'Argo CD Helm release is missing.'; fi
for workload in deployment/argocd-server deployment/argocd-repo-server statefulset/argocd-application-controller deployment/argocd-redis; do
  if kubectl_lab rollout status "$workload" --namespace "$ARGOCD_NAMESPACE" --timeout=30s >/dev/null 2>&1; then
    pass "$workload is Ready."
  else
    fail "$workload is not Ready."
  fi
done
if [ "$(kubectl_lab get deployment argocd-applicationset-controller --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null)" = 0 ]; then pass 'ApplicationSet is inactive at zero replicas.'; else fail 'ApplicationSet is unexpectedly active.'; fi
images=$(kubectl_lab get pods --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{range .items[*].spec.containers[*]}{.image}{"\n"}{end}')
if [ -n "$images" ] && ! printf '%s\n' "$images" | grep -Ev '@sha256:[0-9a-f]{64}$' >/dev/null; then pass 'all running Argo CD images use complete digests.'; else fail 'a running Argo CD image is not digest-pinned.'; fi
if kubectl_lab get service --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{range .items[*]}{.spec.type}{"\n"}{end}' | grep -Ev '^ClusterIP$' >/dev/null; then fail 'Argo CD exposes a non-ClusterIP Service.'; else pass 'Argo CD Services are internal ClusterIP only.'; fi
if kubectl_lab get ingress,httproute --namespace "$ARGOCD_NAMESPACE" --ignore-not-found -o name 2>/dev/null | grep . >/dev/null; then fail 'Argo CD has an external route.'; else pass 'Argo CD has no Ingress or HTTPRoute.'; fi
if kubectl_lab get networkpolicy --namespace "$ARGOCD_NAMESPACE" -o name | grep -F 'argocd-repo-server' >/dev/null; then pass 'repository-server network isolation exists.'; else fail 'repository-server network isolation is missing.'; fi
for project in platform-bootstrap platform-apps; do
  if kubectl_lab get appproject "$project" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then pass "AppProject $project exists."; else fail "AppProject $project is missing."; fi
done
for application in "$ARGOCD_ROOT_APPLICATION" "$ARGOCD_APPLICATION"; do
  if kubectl_lab get application "$application" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    automated=$(kubectl_lab get application "$application" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.syncPolicy.automated}' 2>/dev/null || true)
    finalizers=$(kubectl_lab get application "$application" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.metadata.finalizers}' 2>/dev/null || true)
    [ -z "$automated" ] && pass "$application automatic synchronization is absent." || fail "$application automatic synchronization is enabled."
    [ -z "$finalizers" ] && pass "$application has no cascading-deletion finalizer." || fail "$application has an unexpected finalizer."
  fi
done
if require_argocd_application 2>/dev/null; then
  accepted=$(kubectl_lab get application "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.status.health.status}' 2>/dev/null || true)
  [ -n "$accepted" ] && pass "Application health is reported as $accepted." || fail 'Application health is not reported.'
fi
printf '\nSummary: %s PASS, %s FAIL\n' "$PASS_COUNT" "$FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ]
