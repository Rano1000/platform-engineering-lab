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

expected_image=$(image_ref)
for node in "$CLUSTER_NAME-worker" "$CLUSTER_NAME-worker2"; do
  if docker exec "$node" crictl images 2>/dev/null | grep -F "$APP_NAME" | grep -F "$(image_tag)" >/dev/null 2>&1; then
    pass "$expected_image is present on $node."
  else
    fail "$expected_image is missing from $node."
  fi
done

if kubectl_lab rollout status "deployment/$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" --timeout=60s >/dev/null 2>&1; then pass 'application rollout is healthy.'; else fail 'application rollout is not healthy.'; fi
ready=$(kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
if [ "$ready" = "$APP_REPLICAS" ]; then pass "exactly $APP_REPLICAS replicas are Ready."; else fail "expected $APP_REPLICAS Ready replicas; found ${ready:-0}."; fi

nodes=$(kubectl_lab get pods --namespace "$APP_NAMESPACE" -l "app.kubernetes.io/instance=$APP_RELEASE,app.kubernetes.io/name=$APP_NAME" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | awk 'NF {count++} END {print count + 0}')
if [ "$nodes" -eq 2 ]; then pass 'replicas are distributed across two workers.'; else fail "replicas occupy $nodes distinct node(s)."; fi

endpoints=$(kubectl_lab get endpointslice --namespace "$APP_NAMESPACE" -l "kubernetes.io/service-name=$APP_SERVICE" -o jsonpath='{range .items[*].endpoints[*]}{range .conditions.ready}{.}{"\n"}{end}{end}' | grep -c '^true$' || true)
if [ "$endpoints" -eq 2 ]; then pass 'Service has two Ready endpoints.'; else fail "Service has $endpoints Ready endpoint(s)."; fi

route_accepted=$(kubectl_lab get httproute "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" -o jsonpath='{range .status.parents[*].conditions[?(@.type=="Accepted")]}{.status}{end}' 2>/dev/null || true)
if [ "$route_accepted" = True ]; then pass 'application HTTPRoute is accepted.'; else fail 'application HTTPRoute is missing or not accepted.'; fi
if kubectl_lab get hpa "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" >/dev/null 2>&1; then fail 'HPA exists although autoscaling is disabled.'; else pass 'HPA is absent while Metrics Server is unavailable.'; fi
if kubectl_lab get pdb "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" >/dev/null 2>&1; then pass 'PodDisruptionBudget exists.'; else fail 'PodDisruptionBudget is missing.'; fi
if kubectl_lab get networkpolicy "$APP_DEPLOYMENT-allow-approved-ingress" --namespace "$APP_NAMESPACE" >/dev/null 2>&1; then pass 'application ingress policy exists.'; else fail 'application ingress policy is missing.'; fi

proxy=/api/v1/namespaces/$APP_NAMESPACE/services/http:$APP_SERVICE:80/proxy
if kubectl_lab get --raw="$proxy/" 2>/dev/null | grep -F '"name":"golden-path-api"' >/dev/null 2>&1; then pass 'root endpoint responds through the Service.'; else fail 'root endpoint validation failed.'; fi
if kubectl_lab get --raw="$proxy/health/live" 2>/dev/null | grep -F '"status":"alive"' >/dev/null 2>&1; then pass 'liveness endpoint responds.'; else fail 'liveness endpoint validation failed.'; fi
if kubectl_lab get --raw="$proxy/health/ready" 2>/dev/null | grep -F '"status":"ready"' >/dev/null 2>&1; then pass 'readiness endpoint responds.'; else fail 'readiness endpoint validation failed.'; fi
if kubectl_lab get --raw="$proxy/metrics" 2>/dev/null | grep -F 'golden_path_http_requests_total' >/dev/null 2>&1; then pass 'internal metrics endpoint responds.'; else fail 'internal metrics endpoint validation failed.'; fi
if curl --fail --silent --show-error --header 'Host: golden-path-api.localhost' http://127.0.0.1/ | grep -F '"name":"golden-path-api"' >/dev/null 2>&1; then pass 'root endpoint responds through the Gateway on localhost.'; else fail 'Gateway request validation failed.'; fi
for private_path in metrics health/live health/ready; do
  status=$(curl --silent --output /dev/null --write-out '%{http_code}' --header 'Host: golden-path-api.localhost' "http://127.0.0.1/$private_path" || true)
  if [ "$status" = 404 ]; then
    pass "/$private_path is not publicly routed."
  else
    fail "/$private_path returned HTTP ${status:-unreachable}; expected the Gateway's 404 response."
  fi
done

printf '\nSummary: %s PASS, %s FAIL\n' "$PASS_COUNT" "$FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ]
