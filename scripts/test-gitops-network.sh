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
gnt_artifact_base=$REPOSITORY_ROOT/.artifacts/gitops-network
diagnostics=${GITOPS_NETWORK_DIAGNOSTICS:-$gnt_artifact_base/$suffix}
listener="argocd-api-negative-$suffix"
listener_policy=$listener
created_pods=''
diagnostic_pods=''
diagnostics_complete=0
cleanup_failed=0
created_pod_cleanup_attempted=0
identity=''
worker=''
python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir --base "$gnt_artifact_base" --root "$diagnostics" --path "$diagnostics/pods"
python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir --base "$gnt_artifact_base" --root "$diagnostics" --path "$diagnostics/cleanup"

sanitize_file() (
  gnt_sanitize_source=$1
  gnt_sanitize_output=$2
  python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-output --base "$gnt_artifact_base" --root "$diagnostics" --path "$gnt_sanitize_output"
  python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$gnt_sanitize_source" "$gnt_sanitize_output"
)

capture_pod() (
  gnt_capture_pod=$1
  gnt_capture_raw=$temporary/pod-raw/$gnt_capture_pod
  mkdir -p "$gnt_capture_raw"
  if kubectl_lab get pod "$gnt_capture_pod" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    kubectl_lab logs "$gnt_capture_pod" --namespace "$ARGOCD_NAMESPACE" >"$gnt_capture_raw/pod.log" 2>&1 || true
    kubectl_lab get pod "$gnt_capture_pod" --namespace "$ARGOCD_NAMESPACE" -o json >"$gnt_capture_raw/pod.json"
    kubectl_lab describe pod "$gnt_capture_pod" --namespace "$ARGOCD_NAMESPACE" >"$gnt_capture_raw/describe.txt" 2>&1 || true
    kubectl_lab get events --namespace "$ARGOCD_NAMESPACE" --field-selector "involvedObject.name=$gnt_capture_pod" -o json >"$gnt_capture_raw/events.json"
  fi
)

sanitize_pod() (
  gnt_sanitize_pod=$1
  gnt_sanitize_raw=$temporary/pod-raw/$gnt_sanitize_pod
  gnt_sanitize_destination=$diagnostics/pods/$gnt_sanitize_pod
  [ -d "$gnt_sanitize_raw" ] || return 0
  python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir --base "$gnt_artifact_base" --root "$diagnostics" --path "$gnt_sanitize_destination"
  for gnt_sanitize_name in pod.log pod.json describe.txt events.json; do
    [ -f "$gnt_sanitize_raw/$gnt_sanitize_name" ] || continue
    sanitize_file "$gnt_sanitize_raw/$gnt_sanitize_name" "$gnt_sanitize_destination/$gnt_sanitize_name"
  done
)

capture_diagnostics() (
  gnt_capture_endpoint=$diagnostics/endpoint-identity.json
  gnt_capture_endpointslices=$diagnostics/endpointslices.json
  gnt_capture_node=$diagnostics/node.json
  gnt_capture_policies=$diagnostics/networkpolicies.yaml
  [ -n "$identity" ] && [ -n "$worker" ] || return 1
  # shellcheck disable=SC2086 # Internal Pod names are stored as a whitespace-delimited list.
  for gnt_capture_name in $created_pods; do capture_pod "$gnt_capture_name"; done
  capture_pod "$listener"
  kubectl_lab get networkpolicy --namespace "$ARGOCD_NAMESPACE" -o yaml >"$temporary/networkpolicies.yaml"
  cp "$identity" "$temporary/endpoint-identity.json"
  kubectl_lab get endpointslice --namespace default -l kubernetes.io/service-name=kubernetes -o json >"$temporary/endpointslices.json"
  kubectl_lab get node "$worker" -o json >"$temporary/node.json"
  # shellcheck disable=SC2086 # Internal Pod names are stored as a whitespace-delimited list.
  for gnt_capture_name in $created_pods; do sanitize_pod "$gnt_capture_name"; done
  sanitize_pod "$listener"
  sanitize_file "$temporary/endpoint-identity.json" "$gnt_capture_endpoint"
  sanitize_file "$temporary/endpointslices.json" "$gnt_capture_endpointslices"
  sanitize_file "$temporary/node.json" "$gnt_capture_node"
  sanitize_file "$temporary/networkpolicies.yaml" "$gnt_capture_policies"
)

validate_diagnostics() (
  for gnt_validate_required in endpoint-identity.json endpointslices.json node.json networkpolicies.yaml; do
    [ -s "$diagnostics/$gnt_validate_required" ] || return 1
  done
  # shellcheck disable=SC2086 # Internal Pod names are stored as a whitespace-delimited list.
  for gnt_validate_pod in $diagnostic_pods; do
    for gnt_validate_required in pod.json pod.log describe.txt events.json; do
      [ -s "$diagnostics/pods/$gnt_validate_pod/$gnt_validate_required" ] || return 1
    done
  done
  # The probe Pods contain no environment variables or credential mounts. Reject rather than redact any credential-bearing evidence.
  if find "$diagnostics" -type l -print -quit | grep . >/dev/null; then return 1; fi
  if find "$diagnostics" ! -type d ! -type f -print -quit | grep . >/dev/null; then return 1; fi
  find "$diagnostics" -type f -print0 | xargs -0 python3 "$SCRIPT_DIR/redact-network-diagnostics.py"
)

cleanup_resource() (
  gnt_cleanup_kind=$1 gnt_cleanup_name=$2 gnt_cleanup_uid=$3
  gnt_cleanup_slug=$(printf '%s-%s' "$gnt_cleanup_kind" "$gnt_cleanup_name" | tr '/' '_')
  gnt_cleanup_output=$diagnostics/cleanup/$gnt_cleanup_slug.json
  python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-output --base "$gnt_artifact_base" --root "$diagnostics" --path "$gnt_cleanup_output"
  python3 "$SCRIPT_DIR/cleanup-kubernetes-resource.py" cleanup \
    --context "$EXPECTED_CONTEXT" --kind "$gnt_cleanup_kind" --namespace "$ARGOCD_NAMESPACE" \
    --name "$gnt_cleanup_name" --uid "$gnt_cleanup_uid" --timeout-seconds "$OUTER_TIMEOUT_SECONDS" \
    --output "$gnt_cleanup_output"
)

cleanup_resources() {
  gnt_cleanup_status=0
  if [ -n "${created_pod_uid:-}" ] && [ "$created_pod_cleanup_attempted" -eq 0 ]; then
    cleanup_resource pod "$created_pods" "$created_pod_uid" || gnt_cleanup_status=1
  fi
  if [ -n "${listener_policy_uid:-}" ]; then
    cleanup_resource networkpolicy "$listener_policy" "$listener_policy_uid" || gnt_cleanup_status=1
  fi
  if [ -n "${listener_uid:-}" ]; then
    cleanup_resource pod "$listener" "$listener_uid" || gnt_cleanup_status=1
  fi
  return "$gnt_cleanup_status"
}

finish() {
  gnt_finish_status=$?
  trap - EXIT
  set +e
  capture_diagnostics
  if validate_diagnostics; then
    diagnostics_complete=1
  else
    printf 'FAIL  diagnostics are incomplete or contain credential-bearing data; temporary resources were preserved.\n' >&2
    gnt_finish_status=1
  fi
  if [ "$diagnostics_complete" = 1 ]; then
    cleanup_resources
    gnt_finish_cleanup_status=$?
    if [ "$gnt_finish_cleanup_status" -ne 0 ]; then
      cleanup_failed=1
      printf 'FAIL  one or more temporary resources failed UID-safe cleanup; see retained cleanup evidence.\n' >&2
    fi
  fi
  rm -rf "$temporary"
  printf 'Network diagnostics: %s\n' "$diagnostics"
  if [ "$gnt_finish_status" -eq 0 ] && [ "$cleanup_failed" -ne 0 ]; then gnt_finish_status=1; fi
  exit "$gnt_finish_status"
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
listener_uid=$(kubectl_lab get pod "$listener" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.metadata.uid}')
[ -n "$listener_uid" ] || die 'Temporary negative listener UID is missing.'
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
listener_policy_uid=$(kubectl_lab get networkpolicy "$listener_policy" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.metadata.uid}')
[ -n "$listener_policy_uid" ] || die 'Temporary negative listener policy UID is missing.'

validate_result() (
  gnt_result_log=$1 gnt_result_status=$2 gnt_result_name=$3 gnt_result_identity=$4
  gnt_result_node=$5 gnt_result_host=$6 gnt_result_port=$7 gnt_result_expected=$8
  python3 - "$gnt_result_log" "$gnt_result_status" "$gnt_result_name" "$gnt_result_identity" "$gnt_result_node" "$gnt_result_host" "$gnt_result_port" "$gnt_result_expected" <<'PY'
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
)

run_case() {
  gnt_case_name=$1 gnt_case_identity=$2 gnt_case_labels=$3 gnt_case_host=$4
  gnt_case_port=$5 gnt_case_expected=$6 gnt_case_mode=$7
  gnt_case_pod="$gnt_case_name-$suffix"
  created_pods=$gnt_case_pod
  diagnostic_pods="$diagnostic_pods $gnt_case_pod"
  gnt_case_overrides=$(python3 "$SCRIPT_DIR/network-probe.py" pod-overrides --node "$worker" --image "$image" --test-name "$gnt_case_name" --identity "$gnt_case_identity" --host "$gnt_case_host" --port "$gnt_case_port" --expected "$gnt_case_expected" --mode "$gnt_case_mode" --timeout "$INNER_TIMEOUT_SECONDS")
  kubectl_lab run "$gnt_case_pod" --namespace "$ARGOCD_NAMESPACE" --restart=Never --image="$image" --labels="$gnt_case_labels" --overrides="$gnt_case_overrides"
  created_pod_uid=$(kubectl_lab get pod "$gnt_case_pod" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.metadata.uid}')
  [ -n "$created_pod_uid" ] || return 1
  created_pod_cleanup_attempted=0
  gnt_case_elapsed=0 gnt_case_phase=''
  while [ "$gnt_case_elapsed" -lt "$OUTER_TIMEOUT_SECONDS" ]; do
    gnt_case_phase=$(kubectl_lab get pod "$gnt_case_pod" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case $gnt_case_phase in Succeeded|Failed) break ;; esac
    sleep 1; gnt_case_elapsed=$((gnt_case_elapsed + 1))
  done
  capture_diagnostics
  [ "$gnt_case_phase" = Succeeded ] || return 1
  validate_result "$diagnostics/pods/$gnt_case_pod/pod.log" "$diagnostics/pods/$gnt_case_pod/pod.json" "$gnt_case_name" "$gnt_case_identity" "$worker" "$gnt_case_host" "$gnt_case_port" "$gnt_case_expected"
  created_pod_cleanup_attempted=1
  cleanup_resource pod "$gnt_case_pod" "$created_pod_uid"
  created_pods=''
  created_pod_uid=''
  created_pod_cleanup_attempted=0
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
