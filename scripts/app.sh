#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"

test_app() {
  require_command docker
  docker build --target test --tag "$APP_NAME:test-$(short_revision)" "$APP_CONTEXT"
}

build_app() {
  require_command docker
  require_clean_build_sources
  revision=$(full_revision)
  reference=$(image_ref)
  if docker image inspect "$reference" >/dev/null 2>&1; then
    die "Image '$reference' already exists. Refusing to overwrite an immutable local tag."
  fi
  docker build --target runtime --build-arg "APP_VERSION=$APP_VERSION" --build-arg "VCS_REF=$revision" --tag "$reference" "$APP_CONTEXT"
  configured_revision=$(docker image inspect "$reference" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$configured_revision" = "$revision" ] || die 'Built image revision label does not match Git.'
  printf "Built immutable local image '%s'.\n" "$reference"
}

load_app() {
  require_lab_runtime
  require_clean_build_sources
  reference=$(image_ref)
  docker image inspect "$reference" >/dev/null 2>&1 || die "Build '$reference' before loading it."
  kind load docker-image "$reference" --name "$CLUSTER_NAME"
}

deploy_app() {
  require_command helm
  require_lab_runtime
  refuse_helm_mutation_when_gitops_owned
  require_clean_build_sources
  reference=$(image_ref)
  docker image inspect "$reference" >/dev/null 2>&1 || die "Local image '$reference' is missing."
  kubectl_lab get crd httproutes.gateway.networking.k8s.io >/dev/null 2>&1 || die 'Gateway API Standard CRDs are not installed.'
  kubectl_lab get gateway platform-gateway --namespace platform-system >/dev/null 2>&1 || die 'Platform Gateway is not installed.'
  helm upgrade --install "$APP_RELEASE" "$APP_CHART" \
    --kube-context "$EXPECTED_CONTEXT" \
    --namespace "$APP_NAMESPACE" \
    --set-string "image.tag=$(image_tag)" \
    --set-string "image.revision=$(full_revision)" \
    --atomic --wait --timeout 180s
}

status_app() {
  require_command helm
  require_lab_runtime
  require_app_release
  helm --kube-context "$EXPECTED_CONTEXT" status "$APP_RELEASE" --namespace "$APP_NAMESPACE"
  kubectl_lab get deployment,pods,service,httproute --namespace "$APP_NAMESPACE" -l "app.kubernetes.io/instance=$APP_RELEASE" -o wide
}

uninstall_app() {
  require_command helm
  require_lab_runtime
  refuse_helm_mutation_when_gitops_owned
  require_app_release
  confirm_exact "$APP_RELEASE" "This removes only Helm release '$APP_RELEASE' from namespace '$APP_NAMESPACE'."
  helm uninstall "$APP_RELEASE" --kube-context "$EXPECTED_CONTEXT" --namespace "$APP_NAMESPACE" --wait
}

ownership_status() {
  require_lab_runtime
  if argo_application_owns_workload; then
    printf '%s\n' "ACTIVE OWNER  Argo Application '$ARGO_APPLICATION_NAMESPACE/$ARGO_APPLICATION_NAME'."
    printf '%s\n' "HISTORICAL    Helm release '$APP_NAMESPACE/$APP_RELEASE'; mutation targets are guarded."
  elif argo_application_exists; then
    printf '%s\n' "PENDING OWNER Argo Application '$ARGO_APPLICATION_NAMESPACE/$ARGO_APPLICATION_NAME' exists but has not adopted the Deployment."
    printf '%s\n' "ACTIVE OWNER  Helm release '$APP_NAMESPACE/$APP_RELEASE'. Avoid Helm mutation during the reviewed adoption window."
  elif helm --kube-context "$EXPECTED_CONTEXT" status "$APP_RELEASE" --namespace "$APP_NAMESPACE" >/dev/null 2>&1; then
    printf '%s\n' "ACTIVE OWNER  Helm release '$APP_NAMESPACE/$APP_RELEASE'."
  else
    printf '%s\n' 'ACTIVE OWNER  none detected.'
  fi
}

network_test() {
  require_command helm
  require_lab_runtime
  require_app_release
  reference=$(image_ref)
  suffix="$(date +%s)-$$"
  allowed="metrics-allowed-$suffix"
  denied="metrics-denied-$suffix"
  cleanup() {
    kubectl_lab delete pod "$allowed" "$denied" --namespace observability --ignore-not-found --wait=false >/dev/null 2>&1 || true
  }
  pod_overrides() {
    printf '{"spec":{"automountServiceAccountToken":false,"securityContext":{"runAsNonRoot":true,"runAsUser":10001,"runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"%s","image":"%s","command":["python","-c"],"args":["%s"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}}]}}' "$1" "$reference" "$2"
  }
  trap cleanup EXIT HUP INT TERM
  printf '%s\n' 'This test creates two uniquely named temporary Pods in observability, verifies one allowed and one denied connection, and removes both.'
  allowed_command="import urllib.request; data=urllib.request.urlopen('http://$APP_SERVICE.$APP_NAMESPACE.svc:80/metrics', timeout=5).read(); assert b'golden_path_http_requests_total' in data"
  kubectl_lab run "$allowed" --namespace observability --restart=Never --image="$reference" \
    --labels='platform.engineering-lab/purpose=metrics-test' --overrides="$(pod_overrides "$allowed" "$allowed_command")"
  kubectl_lab wait --namespace observability --for=jsonpath='{.status.phase}'=Succeeded "pod/$allowed" --timeout=30s
  denied_command="import urllib.request; urllib.request.urlopen('http://$APP_SERVICE.$APP_NAMESPACE.svc:80/metrics', timeout=5)"
  kubectl_lab run "$denied" --namespace observability --restart=Never --image="$reference" \
    --overrides="$(pod_overrides "$denied" "$denied_command")"
  if kubectl_lab wait --namespace observability --for=jsonpath='{.status.phase}'=Succeeded "pod/$denied" --timeout=15s >/dev/null 2>&1; then
    die 'Unapproved metrics traffic unexpectedly succeeded.'
  fi
  if ! kubectl_lab wait --namespace observability --for=jsonpath='{.status.phase}'=Failed "pod/$denied" --timeout=30s >/dev/null 2>&1; then
    die 'Unapproved metrics test did not reach a conclusive failed state.'
  fi
  printf '%s\n' 'Network policy test passed: approved metrics traffic succeeded and unapproved traffic was denied.'
}

recovery_test() {
  require_command helm
  require_lab_runtime
  require_app_release
  pod=$(kubectl_lab get pods --namespace "$APP_NAMESPACE" -l "app.kubernetes.io/instance=$APP_RELEASE,app.kubernetes.io/name=$APP_NAME" -o jsonpath='{.items[0].metadata.name}')
  [ -n "$pod" ] || die 'No application Pod is available for the recovery test.'
  confirm_exact "$pod" "This deletes only application Pod '$APP_NAMESPACE/$pod'. Its Deployment should create a replacement."
  old_uid=$(kubectl_lab get pod "$pod" --namespace "$APP_NAMESPACE" -o jsonpath='{.metadata.uid}')
  kubectl_lab delete pod "$pod" --namespace "$APP_NAMESPACE" --wait=false
  kubectl_lab wait --for=delete "pod/$pod" --namespace "$APP_NAMESPACE" --timeout=60s
  kubectl_lab rollout status "deployment/$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" --timeout=120s
  kubectl_lab wait --for=condition=Available "deployment/$APP_DEPLOYMENT" --namespace "$APP_NAMESPACE" --timeout=60s
  new_uids=$(kubectl_lab get pods --namespace "$APP_NAMESPACE" -l "app.kubernetes.io/instance=$APP_RELEASE,app.kubernetes.io/name=$APP_NAME" -o jsonpath='{range .items[*]}{.metadata.uid}{"\n"}{end}')
  if printf '%s\n' "$new_uids" | grep -Fx "$old_uid" >/dev/null 2>&1; then
    die 'The original Pod still exists; recovery could not be confirmed.'
  fi
  count=$(printf '%s\n' "$new_uids" | awk 'NF {count++} END {print count + 0}')
  [ "$count" -eq "$APP_REPLICAS" ] || die "Expected $APP_REPLICAS recovered Pods; found $count."
  printf '%s\n' 'Recovery test passed: the Deployment restored the deleted application Pod.'
}

usage() {
  printf 'usage: %s {test|build|load|deploy|status|validate|uninstall|ownership-status|network-test|recovery-test}\n' "$0" >&2
  exit 2
}

case ${1:-} in
  test) test_app ;;
  build) build_app ;;
  load) load_app ;;
  deploy) deploy_app ;;
  status) status_app ;;
  validate) "$SCRIPT_DIR/validate-app.sh" ;;
  uninstall) uninstall_app ;;
  ownership-status) ownership_status ;;
  network-test) network_test ;;
  recovery-test) recovery_test ;;
  *) usage ;;
esac
