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
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
if resolve_argocd_api_endpoint "$temporary" validation >/dev/null 2>&1 &&
  verify_live_argocd_api_policies "$temporary/validation-identity.json" "$temporary/live-policies.json" >/dev/null 2>&1; then
  pass 'generated API policies match the current verified endpoint identity.'
else
  fail 'generated API policies do not match the current verified endpoint identity.'
fi
if helm --kube-context "$EXPECTED_CONTEXT" status "$ARGOCD_RELEASE" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then pass 'Argo CD Helm release exists.'; else fail 'Argo CD Helm release is missing.'; fi
if kubectl_lab get secret argocd-redis --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
  pass 'Redis initialization reached the Kubernetes API and created its Secret.'
else
  fail 'Redis initialization Secret is missing; verify hook access to Kubernetes API TCP 443.'
fi
for workload in deployment/argocd-server deployment/argocd-repo-server statefulset/argocd-application-controller deployment/argocd-redis; do
  if kubectl_lab rollout status "$workload" --namespace "$ARGOCD_NAMESPACE" --timeout=30s >/dev/null 2>&1; then
    pass "$workload is Ready."
  else
    fail "$workload is not Ready."
  fi
done
control_plane=$(kubectl_lab get nodes -l node-role.kubernetes.io/control-plane -o jsonpath='{.items[0].metadata.name}')
for workload in deployment/argocd-server statefulset/argocd-application-controller; do
  nodes=$(kubectl_lab get pods --namespace "$ARGOCD_NAMESPACE" -l "app.kubernetes.io/name=$(printf '%s' "$workload" | sed 's|.*/||')" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}')
  if [ -n "$nodes" ] && ! printf '%s\n' "$nodes" | grep -Fx "$control_plane" >/dev/null; then
    pass "$workload runs away from the control plane."
  else
    fail "$workload is missing or runs on the control plane."
  fi
done
if [ "$(kubectl_lab get deployment argocd-applicationset-controller --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null)" = 0 ]; then pass 'ApplicationSet is inactive at zero replicas.'; else fail 'ApplicationSet is unexpectedly active.'; fi
images=$(kubectl_lab get pods --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{range .items[*].spec.containers[*]}{.image}{"\n"}{end}')
if [ -n "$images" ] && ! printf '%s\n' "$images" | grep -Ev '@sha256:[0-9a-f]{64}$' >/dev/null; then pass 'all running Argo CD images use complete digests.'; else fail 'a running Argo CD image is not digest-pinned.'; fi
if kubectl_lab get service --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{range .items[*]}{.spec.type}{"\n"}{end}' | grep -Ev '^ClusterIP$' >/dev/null; then fail 'Argo CD exposes a non-ClusterIP Service.'; else pass 'Argo CD Services are internal ClusterIP only.'; fi
if kubectl_lab get ingress,httproute --namespace "$ARGOCD_NAMESPACE" --ignore-not-found -o name 2>/dev/null | grep . >/dev/null; then fail 'Argo CD has an external route.'; else pass 'Argo CD has no Ingress or HTTPRoute.'; fi
if kubectl_lab get networkpolicy --namespace "$ARGOCD_NAMESPACE" -o name | grep -F 'argocd-repo-server' >/dev/null; then pass 'repository-server network isolation exists.'; else fail 'repository-server network isolation is missing.'; fi
if kubectl_lab get appproject default --namespace "$ARGOCD_NAMESPACE" -o json >"$temporary/default-project.json" 2>"$temporary/default-project.err"; then
  default_checksum=$(python3 "$SCRIPT_DIR/validate-default-appproject.py" \
    --expected "$ARGOCD_DEFAULT_PROJECT" --live "$temporary/default-project.json" 2>"$temporary/default-project-validation.err" || true)
  if [ "$default_checksum" = "$ARGOCD_DEFAULT_PROJECT_SHA256" ]; then
    pass "default AppProject is repository-owned and deny-all ($default_checksum)."
  else
    fail 'default AppProject is permissive or differs from repository ownership.'
  fi
else
  fail 'default AppProject is missing or cannot be read.'
fi
for project in platform-bootstrap platform-apps; do
  if kubectl_lab get appproject "$project" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    pass "AppProject $project exists."
  else
    pass "AppProject $project is absent; controller-only installation remains unbootstrapped."
  fi
done
for application in "$ARGOCD_ROOT_APPLICATION" "$ARGOCD_APPLICATION"; do
  if kubectl_lab get application "$application" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    automated=$(kubectl_lab get application "$application" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.syncPolicy.automated}' 2>/dev/null || true)
    finalizers=$(kubectl_lab get application "$application" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.metadata.finalizers}' 2>/dev/null || true)
    if [ -z "$automated" ]; then pass "$application automatic synchronization is absent."; else fail "$application automatic synchronization is enabled."; fi
    if [ -z "$finalizers" ]; then pass "$application has no cascading-deletion finalizer."; else fail "$application has an unexpected finalizer."; fi
  fi
done
if application_state=$(python3 "$SCRIPT_DIR/check-optional-argo-application.py" \
  --context "$EXPECTED_CONTEXT" --namespace "$ARGOCD_NAMESPACE" --name "$ARGOCD_APPLICATION" 2>"$temporary/application-lookup.err"); then
  case $application_state in
    absent) pass "Application $ARGOCD_APPLICATION is absent as expected before bootstrap." ;;
    present)
      accepted=$(kubectl_lab get application "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.status.health.status}' 2>/dev/null || true)
      if [ -n "$accepted" ]; then pass "Application health is reported as $accepted."; else fail 'Application is present but health is not reported.'; fi ;;
    *) fail "optional Application lookup returned an unknown state: $application_state." ;;
  esac
else
  fail "optional Application lookup failed safely: ${application_state:-unknown}."
fi
printf '\nSummary: %s PASS, %s FAIL\n' "$PASS_COUNT" "$FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ]
