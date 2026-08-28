#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"
# shellcheck source=SCRIPTDIR/lib/gitops-common.sh
. "$SCRIPT_DIR/lib/gitops-common.sh"

INNER_TIMEOUT_SECONDS=2
OUTER_TIMEOUT_SECONDS=20
require_lab_runtime
require_app_release
temporary=$(mktemp -d)
suffix="$(date +%s)-$$"
diagnostics=${GITOPS_NETWORK_DIAGNOSTICS:-$REPOSITORY_ROOT/.artifacts/gitops-network/$suffix}
listener="argocd-api-negative-$suffix"
listener_policy=$listener
created_pods=''
diagnostic_pods=''
diagnostics_complete=0
identity=''
worker=''
mkdir -p "$diagnostics/pods"

sanitize_file() {
  source=$1 destination=$2
  python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$source" "$destination"
}

capture_pod() {
  pod=$1
  destination=$diagnostics/pods/$pod
  mkdir -p "$destination"
  if kubectl_lab get pod "$pod" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    kubectl_lab get pod "$pod" --namespace "$ARGOCD_NAMESPACE" -o json >"$temporary/pod.json"
    kubectl_lab logs "$pod" --namespace "$ARGOCD_NAMESPACE" >"$temporary/pod.log" 2>&1 || true
    kubectl_lab describe pod "$pod" --namespace "$ARGOCD_NAMESPACE" >"$temporary/describe.txt" 2>&1 || true
    kubectl_lab get events --namespace "$ARGOCD_NAMESPACE" --field-selector "involvedObject.name=$pod" -o json >"$temporary/events.json"
    sanitize_file "$temporary/pod.json" "$destination/pod.json"
    sanitize_file "$temporary/pod.log" "$destination/pod.log"
    sanitize_file "$temporary/describe.txt" "$destination/describe.txt"
    sanitize_file "$temporary/events.json" "$destination/events.json"
  fi
}

capture_diagnostics() {
  [ -n "$identity" ] && [ -n "$worker" ] || return 1
  sanitize_file "$identity" "$diagnostics/endpoint-identity.json"
  kubectl_lab get endpointslice --namespace default -l kubernetes.io/service-name=kubernetes -o json >"$temporary/endpointslices.json"
  kubectl_lab get node "$worker" -o json >"$temporary/node.json"
  kubectl_lab get networkpolicy --namespace "$ARGOCD_NAMESPACE" -o yaml >"$temporary/networkpolicies.yaml"
  sanitize_file "$temporary/endpointslices.json" "$diagnostics/endpointslices.json"
  sanitize_file "$temporary/node.json" "$diagnostics/node.json"
  sanitize_file "$temporary/networkpolicies.yaml" "$diagnostics/networkpolicies.yaml"
  # shellcheck disable=SC2086 # Internal Pod names are stored as a whitespace-delimited list.
  for pod in $created_pods; do capture_pod "$pod"; done
  capture_pod "$listener"
}

validate_diagnostics() {
  for required in endpoint-identity.json endpointslices.json node.json networkpolicies.yaml; do
    [ -s "$diagnostics/$required" ] || return 1
  done
  # shellcheck disable=SC2086 # Internal Pod names are stored as a whitespace-delimited list.
  for pod in $diagnostic_pods; do
    for required in pod.json pod.log describe.txt events.json; do
      [ -s "$diagnostics/pods/$pod/$required" ] || return 1
    done
  done
  # The probe Pods contain no environment variables or credential mounts. Reject rather than redact any credential-bearing evidence.
  find "$diagnostics" -type f -print0 | xargs -0 python3 "$SCRIPT_DIR/redact-network-diagnostics.py"
}

cleanup_resources() {
  # shellcheck disable=SC2086 # Internal Pod names are stored as a whitespace-delimited list.
  for pod in $created_pods; do
    kubectl_lab delete pod "$pod" --namespace "$ARGOCD_NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  done
  kubectl_lab delete networkpolicy "$listener_policy" --namespace "$ARGOCD_NAMESPACE" --ignore-not-found >/dev/null 2>&1 || true
  kubectl_lab delete pod "$listener" --namespace "$ARGOCD_NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}

finish() {
  status=$?
  set +e
  capture_diagnostics
  if validate_diagnostics; then
    diagnostics_complete=1
  else
    printf 'FAIL  diagnostics are incomplete or contain credential-bearing data; temporary resources were preserved.\n' >&2
    status=1
  fi
  if [ "$diagnostics_complete" = 1 ]; then cleanup_resources; fi
  rm -rf "$temporary"
  printf 'Network diagnostics: %s\n' "$diagnostics"
  exit "$status"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -n "${GITOPS_NETWORK_IDENTITY:-}" ]; then
  identity=$GITOPS_NETWORK_IDENTITY
else
  resolve_argocd_api_endpoint "$temporary" network-test >/dev/null
  identity=$temporary/network-test-identity.json
fi
verify_live_argocd_api_policies "$identity" "$temporary/live-policies.json"

if [ "${GITOPS_NETWORK_NONINTERACTIVE:-0}" != 1 ]; then
  confirm_exact argocd-api-endpoint-network \
    "Create worker-pinned, single-assertion Pods in gitops. Structured diagnostics are captured under .artifacts before cleanup."
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
other_worker=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[1].metadata.name}')
if [ -z "$worker" ] || [ -z "$other_worker" ]; then die 'Two workers are required for the network diagnostics.'; fi
image=$(kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}')
printf '%s\n' "$image" | grep -Eq '(@sha256:[0-9a-f]{64}|:0\.1\.0-[0-9a-f]{12})$' || die "Diagnostic image is not an approved immutable identity: $image"
printf '%s\n' "$image" | grep -Ev '(^|:)latest$' >/dev/null || die 'latest is forbidden for diagnostics.'
image_ids=$(kubectl_lab get pods --namespace "$APP_NAMESPACE" -l app.kubernetes.io/name=golden-path-api -o jsonpath='{range .items[*].status.containerStatuses[*]}{.imageID}{"\n"}{end}')
if [ -z "$image_ids" ] || printf '%s\n' "$image_ids" | grep -Ev 'sha256:[0-9a-f]{64}$' >/dev/null; then
  die 'The diagnostic image runtime identity is not verified by a complete image ID.'
fi

listener_overrides=$(printf '{"spec":{"nodeName":"%s","automountServiceAccountToken":false,"terminationGracePeriodSeconds":1,"securityContext":{"runAsNonRoot":true,"runAsUser":10001,"runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"listener","image":"%s","imagePullPolicy":"IfNotPresent","command":["python","-c"],"args":["import socket; s=socket.socket(); s.bind((\u00270.0.0.0\u0027,6443)); s.listen(); s.accept()"],"ports":[{"containerPort":6443}],"resources":{"requests":{"cpu":"5m","memory":"16Mi"},"limits":{"cpu":"25m","memory":"32Mi"}},"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}}]}}' "$other_worker" "$image")
kubectl_lab run "$listener" --namespace "$ARGOCD_NAMESPACE" --restart=Never --image="$image" --labels="platform.engineering-lab/network-test-listener=$suffix" --overrides="$listener_overrides"
kubectl_lab wait --namespace "$ARGOCD_NAMESPACE" --for=condition=Ready "pod/$listener" --timeout="${OUTER_TIMEOUT_SECONDS}s"
listener_ip=$(kubectl_lab get pod "$listener" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.status.podIP}')
[ -n "$listener_ip" ] || die 'Temporary negative listener has no Pod IP.'
cat >"$temporary/listener-policy.yaml" <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: $listener_policy, namespace: $ARGOCD_NAMESPACE}
spec:
  podSelector: {matchLabels: {platform.engineering-lab/network-test-listener: $suffix}}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: $ARGOCD_NAMESPACE}}
      ports: [{protocol: TCP, port: 6443}]
EOF
kubectl_lab apply -f "$temporary/listener-policy.yaml"

validate_result() {
  log=$1 status_file=$2 expected_name=$3 expected_identity=$4 expected_node=$5 expected_host=$6 expected_port=$7 expected_result=$8
  python3 - "$log" "$status_file" "$expected_name" "$expected_identity" "$expected_node" "$expected_host" "$expected_port" "$expected_result" <<'PY'
import json, sys
path, status_path, name, identity, node, host, port, expected = sys.argv[1:]
lines = [line for line in open(path, encoding="utf-8") if line.strip()]
if len(lines) != 1: raise SystemExit("probe must emit exactly one structured result")
value = json.loads(lines[0])
status = json.load(open(status_path, encoding="utf-8"))
required = {"test_name", "source_identity", "source_node", "destination_ip", "destination_port", "expected_result", "observed_result", "duration_seconds", "exit_code", "error_category"}
if not required.issubset(value): raise SystemExit("probe result is incomplete")
if (value["test_name"], value["source_identity"], value["source_node"], value["destination_ip"], value["destination_port"], value["expected_result"]) != (name, identity, node, host, int(port), expected): raise SystemExit("probe identity differs")
if status["spec"].get("nodeName") != node or "control-plane" in node: raise SystemExit("probe was not pinned to the expected worker")
terminated = status.get("status", {}).get("containerStatuses", [{}])[0].get("state", {}).get("terminated", {})
if terminated.get("exitCode") != value["exit_code"]: raise SystemExit("container termination state differs from structured result")
if value["exit_code"] != 0: raise SystemExit("probe assertion failed: " + json.dumps(value, sort_keys=True))
if value["duration_seconds"] >= 20: raise SystemExit("inner timeout did not complete before outer timeout")
PY
}

run_case() {
  name=$1 identity_name=$2 labels=$3 host=$4 port=$5 expected=$6 mode=$7
  pod="$name-$suffix"
  created_pods=$pod
  diagnostic_pods="$diagnostic_pods $pod"
  overrides=$(python3 "$SCRIPT_DIR/network-probe.py" pod-overrides --node "$worker" --image "$image" --test-name "$name" --identity "$identity_name" --host "$host" --port "$port" --expected "$expected" --mode "$mode" --timeout "$INNER_TIMEOUT_SECONDS")
  kubectl_lab run "$pod" --namespace "$ARGOCD_NAMESPACE" --restart=Never --image="$image" --labels="$labels" --overrides="$overrides"
  elapsed=0 phase=''
  while [ "$elapsed" -lt "$OUTER_TIMEOUT_SECONDS" ]; do
    phase=$(kubectl_lab get pod "$pod" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case $phase in Succeeded|Failed) break ;; esac
    sleep 1; elapsed=$((elapsed + 1))
  done
  capture_pod "$pod"
  [ "$phase" = Succeeded ] || return 1
  validate_result "$diagnostics/pods/$pod/pod.log" "$diagnostics/pods/$pod/pod.json" "$name" "$identity_name" "$worker" "$host" "$port" "$expected"
  kubectl_lab delete pod "$pod" --namespace "$ARGOCD_NAMESPACE" --wait=true >/dev/null
  created_pods=''
}

hook_labels='app.kubernetes.io/name=argocd-redis-secret-init,app.kubernetes.io/component=redis-secret-init,app.kubernetes.io/instance=argocd'
controller_labels='app.kubernetes.io/name=argocd-application-controller,app.kubernetes.io/component=application-controller,app.kubernetes.io/instance=argocd'
server_labels='app.kubernetes.io/name=argocd-server,app.kubernetes.io/component=server,app.kubernetes.io/instance=argocd'
run_case hook-api-allow hook "$hook_labels" "$api_ip" "$api_port" allow api_tls
run_case controller-api-allow controller "$controller_labels" "$api_ip" "$api_port" allow api_tls
run_case server-api-allow server "$server_labels" "$api_ip" "$api_port" allow api_tls
run_case repo-api-deny repository-server 'app.kubernetes.io/name=argocd-repo-server,app.kubernetes.io/component=repo-server,app.kubernetes.io/instance=argocd' "$api_ip" "$api_port" deny tcp
run_case redis-api-deny redis 'app.kubernetes.io/name=argocd-redis,app.kubernetes.io/component=redis,app.kubernetes.io/instance=argocd' "$api_ip" "$api_port" deny tcp
run_case unlabelled-api-deny unlabelled "platform.engineering-lab/network-test=$suffix" "$api_ip" "$api_port" deny tcp
run_case hook-public-443-deny hook "$hook_labels" 1.1.1.1 443 deny tcp
run_case controller-public-443-deny controller "$controller_labels" 1.1.1.1 443 deny tcp
run_case server-public-443-deny server "$server_labels" 1.1.1.1 443 deny tcp
run_case hook-unrelated-6443-deny hook "$hook_labels" "$listener_ip" 6443 deny tcp
run_case controller-unrelated-6443-deny controller "$controller_labels" "$listener_ip" 6443 deny tcp
run_case server-unrelated-6443-deny server "$server_labels" "$listener_ip" 6443 deny tcp

capture_diagnostics
validate_diagnostics
diagnostics_complete=1
printf 'PASS  twelve independently identified worker-pinned network assertions passed.\n'
