#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"

ANT_NAMESPACE=observability
ANT_INNER_TIMEOUT_SECONDS=3
ANT_OUTER_TIMEOUT_SECONDS=30
ANT_MAX_SIMULTANEOUS_RESOURCES=2

require_command kubectl
require_expected_context
kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" >/dev/null ||
  die "Application Deployment '$APP_NAMESPACE/$APP_DEPLOYMENT' is unavailable."
ant_suffix="$(date +%s)-$$"
ant_policy="metrics-test-egress-$ant_suffix"
ant_allowed="metrics-allowed-$ant_suffix"
ant_denied="metrics-denied-$ant_suffix"
ant_artifact_base=$REPOSITORY_ROOT/.artifacts/app-network
ant_diagnostics=${APP_NETWORK_DIAGNOSTICS:-$ant_artifact_base/$ant_suffix}
ant_temporary=$(mktemp -d)
ant_current_pod=''
ant_current_pod_uid=''
ant_policy_uid=''
ant_preserve_resources=0
ant_assertion_status=0
ant_cleanup_status=0

python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir \
  --base "$ant_artifact_base" --root "$ant_diagnostics" --path "$ant_diagnostics/pods"
python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir \
  --base "$ant_artifact_base" --root "$ant_diagnostics" --path "$ant_diagnostics/cleanup"
python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir \
  --base "$ant_artifact_base" --root "$ant_diagnostics" --path "$ant_diagnostics/results"

ant_sanitize_file() (
  ant_sf_source=$1 ant_sf_output=$2
  python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-output \
    --base "$ant_artifact_base" --root "$ant_diagnostics" --path "$ant_sf_output"
  python3 "$SCRIPT_DIR/redact-network-diagnostics.py" --sanitize "$ant_sf_source" "$ant_sf_output"
)

ant_capture_pod() (
  ant_cp_name=$1
  ant_cp_raw=$ant_temporary/raw-pods/$ant_cp_name
  mkdir -p "$ant_cp_raw"
  if kubectl_lab get pod "$ant_cp_name" --namespace "$ANT_NAMESPACE" -o json >"$ant_cp_raw/pod.json"; then
    kubectl_lab logs "$ant_cp_name" --namespace "$ANT_NAMESPACE" >"$ant_cp_raw/pod.log" 2>"$ant_cp_raw/logs.stderr" || true
    kubectl_lab describe pod "$ant_cp_name" --namespace "$ANT_NAMESPACE" >"$ant_cp_raw/describe.txt" 2>&1 || true
    kubectl_lab get events --namespace "$ANT_NAMESPACE" \
      --field-selector "involvedObject.name=$ant_cp_name" -o json >"$ant_cp_raw/events.json"
  fi
)

ant_sanitize_pod() (
  ant_sp_name=$1
  ant_sp_raw=$ant_temporary/raw-pods/$ant_sp_name
  ant_sp_destination=$ant_diagnostics/pods/$ant_sp_name
  [ -d "$ant_sp_raw" ] || return 1
  python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir \
    --base "$ant_artifact_base" --root "$ant_diagnostics" --path "$ant_sp_destination"
  for ant_sp_file in pod.json pod.log logs.stderr describe.txt events.json; do
    [ -f "$ant_sp_raw/$ant_sp_file" ] || continue
    ant_sanitize_file "$ant_sp_raw/$ant_sp_file" "$ant_sp_destination/$ant_sp_file"
  done
)

ant_validate_pod_diagnostics() (
  ant_vpd_name=$1
  ant_vpd_directory=$ant_diagnostics/pods/$ant_vpd_name
  for ant_vpd_file in pod.json pod.log logs.stderr describe.txt events.json; do
    [ -f "$ant_vpd_directory/$ant_vpd_file" ] || return 1
  done
  [ -s "$ant_vpd_directory/pod.json" ] && [ -s "$ant_vpd_directory/pod.log" ] &&
    [ -s "$ant_vpd_directory/describe.txt" ] && [ -s "$ant_vpd_directory/events.json" ] &&
    [ -s "$ant_vpd_directory/pre-test.json" ] && [ -f "$ant_vpd_directory/phase-poll.log" ] || return 1
)

ant_validate_shared_diagnostics() (
  for ant_vsd_file in temporary-policy.yaml application-policy.yaml observability-resources.json nodes.json runtime-identities.json; do
    [ -s "$ant_diagnostics/$ant_vsd_file" ] || return 1
  done
)

ant_cleanup_resource() (
  ant_cr_kind=$1 ant_cr_name=$2 ant_cr_uid=$3
  ant_cr_slug=$(printf '%s-%s' "$ant_cr_kind" "$ant_cr_name" | tr '/' '_')
  ant_cr_output=$ant_diagnostics/cleanup/$ant_cr_slug.json
  python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-output \
    --base "$ant_artifact_base" --root "$ant_diagnostics" --path "$ant_cr_output"
  python3 "$SCRIPT_DIR/cleanup-kubernetes-resource.py" cleanup \
    --context "$EXPECTED_CONTEXT" --kind "$ant_cr_kind" --namespace "$ANT_NAMESPACE" \
    --name "$ant_cr_name" --uid "$ant_cr_uid" --timeout-seconds "$ANT_OUTER_TIMEOUT_SECONDS" \
    --output "$ant_cr_output"
)

ant_validate_cleanup_evidence() (
  ant_vce_kind=$1 ant_vce_name=$2
  ant_vce_slug=$(printf '%s-%s' "$ant_vce_kind" "$ant_vce_name" | tr '/' '_')
  ant_vce_path=$ant_diagnostics/cleanup/$ant_vce_slug.json
  python3 - "$ant_vce_path" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
allowed = {"deleted", "already_absent", "already_absent_after_race"}
if value.get("success") is not True or value.get("cleanupResult") not in allowed:
    raise SystemExit("cleanup evidence is not an approved successful classification")
PY
)

ant_capture_context() (
  kubectl_lab get networkpolicy "$ant_policy" --namespace "$ANT_NAMESPACE" -o yaml >"$ant_temporary/temporary-policy.yaml"
  kubectl_lab get networkpolicy "$APP_RELEASE-$APP_NAME-allow-approved-ingress" \
    --namespace "$APP_NAMESPACE" -o yaml >"$ant_temporary/application-policy.yaml"
  kubectl_lab get pod,networkpolicy --namespace "$ANT_NAMESPACE" -o json >"$ant_temporary/observability-resources.json"
  kubectl_lab get nodes -o json >"$ant_temporary/nodes.json"
  ant_sanitize_file "$ant_temporary/temporary-policy.yaml" "$ant_diagnostics/temporary-policy.yaml"
  ant_sanitize_file "$ant_temporary/application-policy.yaml" "$ant_diagnostics/application-policy.yaml"
  ant_sanitize_file "$ant_temporary/observability-resources.json" "$ant_diagnostics/observability-resources.json"
  ant_sanitize_file "$ant_temporary/nodes.json" "$ant_diagnostics/nodes.json"
  ant_sanitize_file "$ant_temporary/runtime-identities.json" "$ant_diagnostics/runtime-identities.json"
)

ant_validate_global_diagnostics() (
  for ant_vgd_file in temporary-policy.yaml application-policy.yaml observability-resources.json nodes.json runtime-identities.json; do
    [ -s "$ant_diagnostics/$ant_vgd_file" ] || return 1
  done
  for ant_vgd_result in approved-results.json denied-results.json public-metrics.json public-live.json public-ready.json; do
    [ -s "$ant_diagnostics/results/$ant_vgd_result" ] || return 1
  done
  if find "$ant_diagnostics" -type l -print -quit | grep . >/dev/null; then return 1; fi
  if find "$ant_diagnostics" ! -type d ! -type f -print -quit | grep . >/dev/null; then return 1; fi
  find "$ant_diagnostics" -type f -print0 | xargs -0 python3 "$SCRIPT_DIR/redact-network-diagnostics.py"
)

ant_write_evidence_manifest() (
  python3 - "$ant_diagnostics" <<'PY'
import hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
if root.is_symlink() or not root.is_dir():
    raise SystemExit("evidence root is unsafe")
files = {}
for path in sorted(root.rglob("*")):
    if path.name == "evidence-manifest.json":
        continue
    if path.is_symlink() or (not path.is_dir() and not path.is_file()):
        raise SystemExit(f"unsafe evidence entry: {path}")
    if path.is_file():
        files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
document = {"schemaVersion": 1, "files": files}
temporary = root / ".evidence-manifest.json.tmp"
temporary.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
os.replace(temporary, root / "evidence-manifest.json")
PY
)

ant_finish() {
  ant_finish_status=$?
  trap - EXIT
  set +e
  if [ -n "$ant_current_pod" ]; then
    ant_capture_pod "$ant_current_pod"
    ant_sanitize_pod "$ant_current_pod"
    if ! ant_validate_pod_diagnostics "$ant_current_pod"; then ant_preserve_resources=1; fi
    if [ -z "$ant_current_pod_uid" ]; then ant_preserve_resources=1; fi
  fi
  if [ -z "$ant_policy_uid" ] &&
     kubectl_lab get networkpolicy "$ant_policy" --namespace "$ANT_NAMESPACE" \
       -o json >"$ant_temporary/untracked-policy.json" 2>"$ant_temporary/untracked-policy.stderr"; then
    ant_sanitize_file "$ant_temporary/untracked-policy.json" "$ant_diagnostics/untracked-policy.json"
    ant_sanitize_file "$ant_temporary/untracked-policy.stderr" "$ant_diagnostics/untracked-policy.stderr"
    ant_preserve_resources=1
  fi
  if [ "$ant_preserve_resources" -eq 0 ] && [ -n "$ant_current_pod_uid" ]; then
    if ! ant_cleanup_resource pod "$ant_current_pod" "$ant_current_pod_uid" ||
       ! ant_validate_cleanup_evidence pod "$ant_current_pod"; then
      ant_cleanup_status=1
    fi
  fi
  if [ "$ant_preserve_resources" -eq 0 ] && [ -n "$ant_policy_uid" ]; then
    ant_capture_context || ant_preserve_resources=1
    if [ "$ant_preserve_resources" -eq 0 ]; then
      if ! ant_cleanup_resource networkpolicy "$ant_policy" "$ant_policy_uid" ||
         ! ant_validate_cleanup_evidence networkpolicy "$ant_policy"; then
        ant_cleanup_status=1
      fi
    fi
  fi
  ant_write_evidence_manifest || ant_cleanup_status=1
  rm -rf "$ant_temporary"
  printf 'Application network diagnostics: %s\n' "$ant_diagnostics"
  if [ "$ant_preserve_resources" -ne 0 ]; then
    printf 'FAIL  diagnostics were incomplete; exact temporary resources were preserved.\n' >&2
    exit 1
  fi
  if [ "$ant_finish_status" -ne 0 ]; then exit "$ant_finish_status"; fi
  if [ "$ant_assertion_status" -ne 0 ]; then exit "$ant_assertion_status"; fi
  exit "$ant_cleanup_status"
}
trap ant_finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "${APP_NETWORK_NONINTERACTIVE:-0}" != 1 ]; then
  confirm_exact app-network-policy-test \
    "Create at most $ANT_MAX_SIMULTANEOUS_RESOURCES temporary resources in observability; capture sanitized evidence before UID-aware cleanup."
fi

ant_image=$(kubectl_lab get deployment "$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}')
printf '%s\n' "$ant_image" | grep -Eq '^ghcr\.io/rano1000/golden-path-api@sha256:[0-9a-f]{64}$' ||
  die "Network probe image is not the approved immutable registry identity: $ant_image"
ant_image_ids=$(kubectl_lab get pods --namespace "$APP_NAMESPACE" -l app.kubernetes.io/name=golden-path-api \
  -o jsonpath='{range .items[*].status.containerStatuses[*]}{.imageID}{"\n"}{end}')
[ -n "$ant_image_ids" ] || die 'Application runtime image IDs are unavailable.'
if printf '%s\n' "$ant_image_ids" | grep -Ev '@sha256:[0-9a-f]{64}$' >/dev/null; then
  die 'Application runtime image IDs are not complete immutable registry digests.'
fi
ant_worker=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[0].metadata.name}')
ant_other_worker=$(kubectl_lab get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[1].metadata.name}')
if [ -z "$ant_worker" ] || [ -z "$ant_other_worker" ]; then
  die 'Two worker nodes are required.'
fi
ant_service_ip=$(kubectl_lab get service "$APP_SERVICE" --namespace "$APP_NAMESPACE" -o jsonpath='{.spec.clusterIP}')
ant_app_pod_ip=$(kubectl_lab get pod --namespace "$APP_NAMESPACE" -l app.kubernetes.io/name=golden-path-api \
  -o jsonpath='{.items[0].status.podIP}')
ant_api_ip=$(kubectl_lab get endpointslice --namespace default -l kubernetes.io/service-name=kubernetes \
  -o jsonpath='{.items[0].endpoints[0].addresses[0]}')
ant_api_port=$(kubectl_lab get endpointslice --namespace default -l kubernetes.io/service-name=kubernetes \
  -o jsonpath='{.items[0].ports[0].port}')
python3 -c 'import ipaddress,sys; [ipaddress.ip_address(v) for v in sys.argv[1:4]]; assert sys.argv[4].isdigit()' \
  "$ant_service_ip" "$ant_app_pod_ip" "$ant_api_ip" "$ant_api_port"

cat >"$ant_temporary/runtime-identities.json" <<EOF
{"runId":"$ant_suffix","namespace":"$ANT_NAMESPACE","image":"$ant_image","imageIDs":$(printf '%s\n' "$ant_image_ids" | python3 -c 'import json,sys; print(json.dumps([x.strip() for x in sys.stdin if x.strip()]))'),"workers":["$ant_worker","$ant_other_worker"],"applicationServiceIP":"$ant_service_ip","applicationPodIP":"$ant_app_pod_ip","kubernetesAPI":{"address":"$ant_api_ip","port":$ant_api_port},"maximumSimultaneousTemporaryResources":$ANT_MAX_SIMULTANEOUS_RESOURCES}
EOF
kubectl_lab get pod,networkpolicy --namespace "$ANT_NAMESPACE" -o json >"$ant_temporary/observability-before.json"
cat >"$ant_temporary/policy.yaml" <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: $ant_policy
  namespace: $ANT_NAMESPACE
  labels:
    app.kubernetes.io/managed-by: platform-engineering-lab
    platform.engineering-lab/purpose: metrics-test
    platform.engineering-lab/run-id: $ant_suffix
spec:
  podSelector:
    matchLabels:
      platform.engineering-lab/purpose: metrics-test
      platform.engineering-lab/run-id: $ant_suffix
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: $APP_NAMESPACE
          podSelector:
            matchLabels:
              app.kubernetes.io/instance: $APP_RELEASE
              app.kubernetes.io/name: $APP_NAME
      ports:
        - protocol: TCP
          port: 8080
EOF
kubectl_lab create -f "$ant_temporary/policy.yaml"
kubectl_lab get networkpolicy "$ant_policy" --namespace "$ANT_NAMESPACE" -o json >"$ant_temporary/policy-created.json"
ant_policy_uid=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["uid"])' "$ant_temporary/policy-created.json")
[ -n "$ant_policy_uid" ] || die 'Temporary NetworkPolicy UID is missing.'
ant_sanitize_file "$ant_temporary/policy-created.json" "$ant_diagnostics/policy-created.json"
ant_capture_context
ant_validate_shared_diagnostics || die 'Shared NetworkPolicy diagnostics are incomplete before probing.'

cat >"$ant_temporary/approved-cases.json" <<EOF
[{"name":"approved-internal-metrics","identity":"approved-observability","host":"$ant_service_ip","port":80,"expected":"allow","mode":"http","path":"/metrics","expected_status":200,"body_contains":"golden_path_http_requests_total"},{"name":"approved-outside-flow-deny","identity":"approved-observability","host":"$ant_app_pod_ip","port":8081,"expected":"deny","mode":"tcp"},{"name":"approved-internet-deny","identity":"approved-observability","host":"1.1.1.1","port":443,"expected":"deny","mode":"tcp"},{"name":"approved-kubernetes-api-deny","identity":"approved-observability","host":"$ant_api_ip","port":$ant_api_port,"expected":"deny","mode":"tcp"}]
EOF
cat >"$ant_temporary/denied-cases.json" <<EOF
[{"name":"unapproved-internal-metrics-deny","identity":"unapproved-observability","host":"$ant_service_ip","port":80,"expected":"deny","mode":"http","path":"/metrics","expected_status":200},{"name":"unapproved-internet-deny","identity":"unapproved-observability","host":"1.1.1.1","port":443,"expected":"deny","mode":"tcp"},{"name":"unapproved-kubernetes-api-deny","identity":"unapproved-observability","host":"$ant_api_ip","port":$ant_api_port,"expected":"deny","mode":"tcp"}]
EOF

ant_run_case() {
  ant_rc_name=$1 ant_rc_identity=$2 ant_rc_worker=$3 ant_rc_cases=$4 ant_rc_labels=$5
  ant_current_pod=$ant_rc_name
  ant_rc_overrides=$(python3 "$SCRIPT_DIR/app-network-probe.py" pod-overrides --node "$ant_rc_worker" \
    --image "$ant_image" --cases "$ant_rc_cases" --timeout "$ANT_INNER_TIMEOUT_SECONDS")
  kubectl_lab run "$ant_rc_name" --namespace "$ANT_NAMESPACE" --restart=Never --image="$ant_image" \
    --labels="$ant_rc_labels" --overrides="$ant_rc_overrides"
  kubectl_lab get pod "$ant_rc_name" --namespace "$ANT_NAMESPACE" -o json >"$ant_temporary/$ant_rc_name-created.json"
  ant_current_pod_uid=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["uid"])' \
    "$ant_temporary/$ant_rc_name-created.json")
  [ -n "$ant_current_pod_uid" ] || return 2
  ant_sanitize_file "$ant_temporary/$ant_rc_name-created.json" "$ant_diagnostics/pods/$ant_rc_name/pre-test.json"
  ant_rc_elapsed=0 ant_rc_phase=''
  : >"$ant_temporary/$ant_rc_name-phase-poll.log"
  while [ "$ant_rc_elapsed" -lt "$ANT_OUTER_TIMEOUT_SECONDS" ]; do
    ant_rc_phase=$(kubectl_lab get pod "$ant_rc_name" --namespace "$ANT_NAMESPACE" \
      -o jsonpath='{.status.phase}' 2>>"$ant_temporary/$ant_rc_name-phase-poll.log") || ant_rc_phase='api_error'
    case $ant_rc_phase in Succeeded|Failed|api_error) break ;; esac
    sleep 1
    ant_rc_elapsed=$((ant_rc_elapsed + 1))
  done
  ant_capture_pod "$ant_rc_name"
  ant_sanitize_pod "$ant_rc_name"
  ant_sanitize_file "$ant_temporary/$ant_rc_name-phase-poll.log" "$ant_diagnostics/pods/$ant_rc_name/phase-poll.log"
  if ! ant_validate_shared_diagnostics || ! ant_validate_pod_diagnostics "$ant_rc_name"; then
    ant_preserve_resources=1
    return 2
  fi
  ant_rc_result=0
  if [ "$ant_rc_phase" != Succeeded ]; then
    ant_rc_result=1
  fi
  ant_rc_validation_status=0
  python3 "$SCRIPT_DIR/app-network-probe.py" validate-log --cases "$ant_rc_cases" \
    --log "$ant_diagnostics/pods/$ant_rc_name/pod.log" --pod "$ant_diagnostics/pods/$ant_rc_name/pod.json" \
    --uid "$ant_current_pod_uid" --node "$ant_rc_worker" --outer-timeout "$ANT_OUTER_TIMEOUT_SECONDS" \
    >"$ant_diagnostics/results/$ant_rc_identity-results.json" || ant_rc_validation_status=$?
  if [ ! -s "$ant_diagnostics/results/$ant_rc_identity-results.json" ] ||
     ! python3 "$SCRIPT_DIR/redact-network-diagnostics.py" "$ant_diagnostics/results/$ant_rc_identity-results.json"; then
    ant_preserve_resources=1
    return 2
  fi
  if [ "$ant_rc_validation_status" -ne 0 ]; then
    ant_rc_result=1
  fi
  if ! ant_cleanup_resource pod "$ant_rc_name" "$ant_current_pod_uid" ||
     ! ant_validate_cleanup_evidence pod "$ant_rc_name"; then
    ant_cleanup_status=1
    ant_preserve_resources=1
    return 2
  fi
  ant_current_pod=''
  ant_current_pod_uid=''
  return "$ant_rc_result"
}

ant_run_case "$ant_allowed" approved "$ant_worker" "$ant_temporary/approved-cases.json" \
  "platform.engineering-lab/purpose=metrics-test,platform.engineering-lab/run-id=$ant_suffix" || ant_assertion_status=1
[ "$ant_preserve_resources" -eq 0 ] || die 'Approved probe diagnostics are incomplete.'
ant_run_case "$ant_denied" denied "$ant_other_worker" "$ant_temporary/denied-cases.json" \
  "platform.engineering-lab/purpose=unapproved-test,platform.engineering-lab/run-id=$ant_suffix" || ant_assertion_status=1
[ "$ant_preserve_resources" -eq 0 ] || die 'Denied probe diagnostics are incomplete.'

for ant_public_case in metrics live ready; do
  case $ant_public_case in
    metrics) ant_public_path=/metrics ;;
    live) ant_public_path=/health/live ;;
    ready) ant_public_path=/health/ready ;;
  esac
  if ! python3 "$SCRIPT_DIR/app-network-probe.py" host-http --name "public-$ant_public_case-blocked" \
    --url "http://127.0.0.1$ant_public_path" --host-header golden-path-api.localhost \
    --expected-status 404 --timeout "$ANT_INNER_TIMEOUT_SECONDS" \
    >"$ant_diagnostics/results/public-$ant_public_case.json"; then
    ant_assertion_status=1
  fi
done

ant_capture_context
if ant_validate_global_diagnostics; then
  :
else
  ant_preserve_resources=1
  die 'Application network diagnostics are incomplete or unsafe.'
fi
if ! ant_cleanup_resource networkpolicy "$ant_policy" "$ant_policy_uid" ||
   ! ant_validate_cleanup_evidence networkpolicy "$ant_policy"; then
  ant_cleanup_status=1
fi
ant_policy_uid=''
kubectl_lab get pod,networkpolicy --namespace "$ANT_NAMESPACE" -o json >"$ant_temporary/observability-after.json"
python3 - "$ant_temporary/observability-before.json" "$ant_temporary/observability-after.json" "$ant_suffix" <<'PY'
import json, sys
before, after = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:3])
suffix = sys.argv[3]
def normalize(value):
    result = {}
    for item in value["items"]:
        name = item["metadata"]["name"]
        if name.endswith(suffix):
            continue
        result[(item["apiVersion"], item["kind"], name)] = {
            "uid": item["metadata"]["uid"], "resourceVersion": item["metadata"]["resourceVersion"],
            "spec": item.get("spec"),
        }
    return result
if normalize(before) != normalize(after):
    raise SystemExit("an unrelated observability Pod or NetworkPolicy changed")
if any(item["metadata"]["name"].endswith(suffix) for item in after["items"]):
    raise SystemExit("a temporary application network-test resource remains")
print("PASS  all exact temporary resources are absent and unrelated observability resources are unchanged.")
PY

if [ "$ant_assertion_status" -eq 0 ] && [ "$ant_cleanup_status" -eq 0 ]; then
  printf 'PASS  ten independent application network assertions passed with at most %s temporary resources.\n' \
    "$ANT_MAX_SIMULTANEOUS_RESOURCES"
fi
