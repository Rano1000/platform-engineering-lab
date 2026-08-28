#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"

PASS_COUNT=0
FAIL_COUNT=0
pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS  %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL  %s\n' "$*"; }

require_command helm
require_command curl
require_lab_runtime
require_app_release

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
if argo_application_owns_workload; then
  source_kind=argocd
  kubectl_lab get application.argoproj.io "$ARGO_APPLICATION_NAME" --namespace "$ARGO_APPLICATION_NAMESPACE" -o json >"$temporary/source.json"
else
  source_kind=helm
  helm --kube-context "$EXPECTED_CONTEXT" get values "$APP_RELEASE" --namespace "$APP_NAMESPACE" --all -o json >"$temporary/source.json"
fi
kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" -o json >"$temporary/deployment.json"
kubectl_lab get pods --namespace "$APP_NAMESPACE" -l "app.kubernetes.io/instance=$APP_RELEASE,app.kubernetes.io/name=$APP_NAME" -o json >"$temporary/pods.json"
node_arguments=
if [ "$source_kind" = helm ]; then
  for node in "$CLUSTER_NAME-worker" "$CLUSTER_NAME-worker2"; do
    docker exec "$node" crictl images --output json >"$temporary/$node.json"
    node_arguments="$node_arguments --node-images $temporary/$node.json"
  done
fi
# node_arguments contains paths created above and intentionally expands into repeated options.
# shellcheck disable=SC2086
if python3 "$SCRIPT_DIR/validate-app-image.py" --source-kind "$source_kind" --source "$temporary/source.json" \
  --deployment "$temporary/deployment.json" --pods "$temporary/pods.json" $node_arguments; then
  pass 'deployed application image identity is immutable and internally consistent.'
else
  fail 'deployed application image identity validation failed.'
fi

if kubectl_lab rollout status "deployment/$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" --timeout=60s >/dev/null 2>&1; then pass 'application rollout is healthy.'; else fail 'application rollout is not healthy.'; fi
ready=$(kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
if [ "$ready" = "$APP_REPLICAS" ]; then pass "exactly $APP_REPLICAS replicas are Ready."; else fail "expected $APP_REPLICAS Ready replicas; found ${ready:-0}."; fi

nodes=$(kubectl_lab get pods --namespace "$APP_NAMESPACE" -l "app.kubernetes.io/instance=$APP_RELEASE,app.kubernetes.io/name=$APP_NAME" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | awk 'NF {count++} END {print count + 0}')
if [ "$nodes" -eq 2 ]; then pass 'replicas are distributed across two workers.'; else fail "replicas occupy $nodes distinct node(s)."; fi

endpoints=$(kubectl_lab get endpointslice --namespace "$APP_NAMESPACE" -l "kubernetes.io/service-name=$APP_SERVICE" -o jsonpath='{range .items[*].endpoints[*]}{.conditions.ready}{"\n"}{end}' | grep -c '^true$' || true)
if [ "$endpoints" -eq 2 ]; then pass 'Service has two Ready endpoints.'; else fail "Service has $endpoints Ready endpoint(s)."; fi

route_accepted=$(kubectl_lab get httproute "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" -o jsonpath='{range .status.parents[*].conditions[?(@.type=="Accepted")]}{.status}{end}' 2>/dev/null || true)
if [ "$route_accepted" = True ]; then pass 'application HTTPRoute is accepted.'; else fail 'application HTTPRoute is missing or not accepted.'; fi
if kubectl_lab get hpa "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" >/dev/null 2>&1; then fail 'HPA exists although autoscaling is disabled.'; else pass 'HPA is absent while Metrics Server is unavailable.'; fi
if kubectl_lab get pdb "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" >/dev/null 2>&1; then pass 'PodDisruptionBudget exists.'; else fail 'PodDisruptionBudget is missing.'; fi
if kubectl_lab get networkpolicy "$APP_DEPLOYMENT-allow-approved-ingress" --namespace "$APP_NAMESPACE" >/dev/null 2>&1; then pass 'application ingress policy exists.'; else fail 'application ingress policy is missing.'; fi

traefik_pod=$(kubectl_lab get pod --namespace platform-system -l app.kubernetes.io/name=traefik -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
service_url=http://$APP_SERVICE.$APP_NAMESPACE.svc:80
service_get() {
  kubectl_lab exec --namespace platform-system "$traefik_pod" -- wget -T 5 -qO- "$service_url$1" 2>/dev/null
}
if [ -n "$traefik_pod" ] && service_get / | grep -F '"name":"golden-path-api"' >/dev/null 2>&1; then pass 'root endpoint responds through the Service.'; else fail 'root endpoint validation failed.'; fi
if service_get /health/live | grep -F '"status":"alive"' >/dev/null 2>&1; then pass 'liveness endpoint responds through the Service.'; else fail 'liveness endpoint validation failed.'; fi
if service_get /health/ready | grep -F '"status":"ready"' >/dev/null 2>&1; then pass 'readiness endpoint responds through the Service.'; else fail 'readiness endpoint validation failed.'; fi
if service_get /metrics | grep -F 'golden_path_http_requests_total' >/dev/null 2>&1; then pass 'internal metrics endpoint responds through the Service.'; else fail 'internal metrics endpoint validation failed.'; fi

addresses=$(kubectl_lab get endpointslice --namespace "$APP_NAMESPACE" -l "kubernetes.io/service-name=$APP_SERVICE" -o jsonpath='{range .items[*].endpoints[?(@.conditions.ready==true)]}{.addresses[0]}{"\n"}{end}')
reachable=0
for position in 1 2; do
  address=$(printf '%s\n' "$addresses" | sed -n "${position}p")
  if kubectl_lab exec --namespace platform-system "$traefik_pod" -- wget -T 5 -qO- "http://$address:8080/health/ready" 2>/dev/null | grep -F '"status":"ready"' >/dev/null 2>&1; then
    reachable=$((reachable + 1))
  fi
done
if [ "$reachable" -eq 2 ]; then pass 'both Service endpoints are reachable from Traefik.'; else fail "$reachable of 2 Service endpoints are reachable from Traefik."; fi
if curl --fail --silent --show-error --header 'Host: golden-path-api.localhost' http://127.0.0.1/ | grep -F '"name":"golden-path-api"' >/dev/null 2>&1; then pass 'root endpoint responds through the Gateway on localhost.'; else fail 'Gateway request validation failed.'; fi
for private_path in metrics health/live health/ready unknown; do
  status=$(curl --silent --output /dev/null --write-out '%{http_code}' --header 'Host: golden-path-api.localhost' "http://127.0.0.1/$private_path" || true)
  if [ "$status" = 404 ]; then
    pass "/$private_path is not publicly routed."
  else
    fail "/$private_path returned HTTP ${status:-unreachable}; expected the Gateway's 404 response."
  fi
done

printf '\nSummary: %s PASS, %s FAIL\n' "$PASS_COUNT" "$FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ]
