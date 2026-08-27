#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/app-common.sh
. "$SCRIPT_DIR/lib/app-common.sh"
# shellcheck source=SCRIPTDIR/lib/gitops-common.sh
. "$SCRIPT_DIR/lib/gitops-common.sh"

verify_chart() {
  verify_argocd_chart "$1"
}

install_gitops() {
  require_lab_runtime
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  archive=$(verify_chart "$temporary")
  confirm_exact "$CLUSTER_NAME" "Install pinned Argo CD $ARGOCD_VERSION into '$ARGOCD_NAMESPACE' on '$EXPECTED_CONTEXT'. This creates cluster-scoped CRDs and RBAC."
  kubectl_lab apply -f "$ARGOCD_CONFIG/resource-controls.yaml"
  kubectl_lab apply -f "$ARGOCD_CONFIG/network-policies.yaml"
  helm upgrade --install "$ARGOCD_RELEASE" "$archive" --kube-context "$EXPECTED_CONTEXT" \
    --namespace "$ARGOCD_NAMESPACE" --values "$ARGOCD_CONFIG/values.yaml" \
    --atomic --wait --timeout 300s
}

bootstrap_gitops() {
  require_lab_runtime
  helm --kube-context "$EXPECTED_CONTEXT" status "$ARGOCD_RELEASE" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1 ||
    die "Argo CD release '$ARGOCD_RELEASE' is not installed."
  if kubectl_lab get application "$ARGOCD_ROOT_APPLICATION" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    die "Root Application '$ARGOCD_ROOT_APPLICATION' already exists; bootstrap is a one-time operation."
  fi
  confirm_exact "$ARGOCD_ROOT_APPLICATION" "Bootstrap the two restricted AppProjects and root Application once. No workload Application or workload resource is applied directly."
  kubectl_lab apply -f "$ARGOCD_ENVIRONMENT/bootstrap-project.yaml"
  kubectl_lab apply -f "$ARGOCD_ENVIRONMENT/workload-project.yaml"
  kubectl_lab apply -f "$ARGOCD_ENVIRONMENT/root-application.yaml"
}

status_gitops() {
  require_lab_runtime
  helm --kube-context "$EXPECTED_CONTEXT" status "$ARGOCD_RELEASE" --namespace "$ARGOCD_NAMESPACE"
  kubectl_lab get pods,service --namespace "$ARGOCD_NAMESPACE" -o wide
  kubectl_lab get appproject,application --namespace "$ARGOCD_NAMESPACE" -o wide
}

root_status() {
  require_lab_runtime
  require_argocd_root_application
  kubectl_lab get application "$ARGOCD_ROOT_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o wide
}

prepare_environment_revision() {
  destination=$1
  require_clean_synchronized_repository
  application=$destination/golden-path-api.yaml
  evidence=$destination/golden-path-api.json
  manifests=$(git -C "$REPOSITORY_ROOT" ls-tree -r --name-only "$environment_revision" environments/local/gitops/applications |
    awk '/\.yaml$/ {print}')
  [ "$manifests" = environments/local/gitops/applications/golden-path-api.yaml ] ||
    die "environmentRevision $environment_revision contains an unexpected Application manifest set."
  git -C "$REPOSITORY_ROOT" show "$environment_revision:environments/local/gitops/applications/golden-path-api.yaml" >"$application" ||
    die "environmentRevision $environment_revision has no approved child Application."
  git -C "$REPOSITORY_ROOT" show "$environment_revision:environments/local/gitops/evidence/golden-path-api.json" >"$evidence" ||
    die "environmentRevision $environment_revision has no promotion evidence."
  python3 "$SCRIPT_DIR/validate-promotion.py" --evidence "$evidence" --application "$application"
  child_spec_checksum=$(python3 "$SCRIPT_DIR/validate-reconciliation.py" --evidence "$evidence" --application "$application")
  chart_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["chartRevision"])' "$evidence")
  image_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageSourceRevision"])' "$evidence")
  digest=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageDigest"])' "$evidence")
}

root_diff() {
  require_lab_runtime
  require_argocd_cli
  require_argocd_root_application
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  prepare_environment_revision "$temporary"
  printf 'Environment revision: %s\nChild specification SHA-256: %s\n' "$environment_revision" "$child_spec_checksum"
  argocd app diff "$ARGOCD_ROOT_APPLICATION" --core --revision "$environment_revision"
}

root_sync() {
  require_lab_runtime
  require_argocd_cli
  require_argocd_root_application
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  prepare_environment_revision "$temporary"
  root_repo=$(kubectl_lab get application "$ARGOCD_ROOT_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.source.repoURL}')
  root_revision=$(kubectl_lab get application "$ARGOCD_ROOT_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.source.targetRevision}')
  root_path=$(kubectl_lab get application "$ARGOCD_ROOT_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.source.path}')
  if [ "$root_repo" != https://github.com/Rano1000/platform-engineering-lab.git ] ||
    [ "$root_revision" != main ] || [ "$root_path" != environments/local/gitops/applications ]; then
    die 'Live root Application source contract is unexpected.'
  fi
  printf '%s\n' 'Stage 1 changes only the child Application specification in gitops. It does not synchronize or prune workload resources.'
  printf 'Environment revision: %s\nChild specification SHA-256: %s\n' "$environment_revision" "$child_spec_checksum"
  argocd app diff "$ARGOCD_ROOT_APPLICATION" --core --revision "$environment_revision" || diff_status=$?
  case ${diff_status:-0} in 0|1) ;; *) die 'Argo diff failed.' ;; esac
  require_environment_revision_current "$environment_revision"
  confirmation=$EXPECTED_CONTEXT/$ARGOCD_ROOT_APPLICATION/$environment_revision/$chart_revision/$image_revision/$digest/sha256:$child_spec_checksum
  confirm_exact "$confirmation" "Synchronize only root Application '$ARGOCD_ROOT_APPLICATION' from immutable environmentRevision '$environment_revision'."
  require_environment_revision_current "$environment_revision"
  argocd app sync "$ARGOCD_ROOT_APPLICATION" --core --revision "$environment_revision" --prune=false
  kubectl_lab get application "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o json >"$temporary/live-child.json"
  python3 "$SCRIPT_DIR/validate-reconciliation.py" --application "$application" --evidence "$evidence" \
    --live "$temporary/live-child.json" --expected-checksum "$child_spec_checksum"
}

app_status() {
  require_lab_runtime
  require_argocd_application
  kubectl_lab get application "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o wide
}

app_diff() {
  require_lab_runtime
  require_argocd_cli
  require_argocd_application
  argocd app diff "$ARGOCD_APPLICATION" --core
}

app_sync() {
  require_lab_runtime
  require_argocd_cli
  require_argocd_application
  require_clean_synchronized_repository
  application=$ARGOCD_ENVIRONMENT/applications/golden-path-api.yaml
  evidence=$ARGOCD_ENVIRONMENT/evidence/golden-path-api.json
  [ -f "$application" ] || die 'No approved child Application exists in local main.'
  python3 "$SCRIPT_DIR/validate-promotion.py" --evidence "$evidence" --application "$application"
  chart_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["chartRevision"])' "$evidence")
  image_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageSourceRevision"])' "$evidence")
  digest=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageDigest"])' "$evidence")
  live_repo=$(kubectl_lab get application "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.source.repoURL}')
  live_chart=$(kubectl_lab get application "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.source.targetRevision}')
  live_digest=$(kubectl_lab get application "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" -o jsonpath='{.spec.source.helm.valuesObject.image.digest}')
  [ "$live_repo" = https://github.com/Rano1000/platform-engineering-lab.git ] || die 'Live child Application uses an unexpected repository.'
  if [ "$live_chart" != "$chart_revision" ] || [ "$live_digest" != "$digest" ]; then
    die 'Run the approved root sync before workload synchronization.'
  fi
  printf '%s\n' 'Stage 2 changes only resources owned by the child Application. Pruning remains disabled.'
  argocd app diff "$ARGOCD_APPLICATION" --core || diff_status=$?
  case ${diff_status:-0} in 0|1) ;; *) die 'Argo workload diff failed.' ;; esac
  confirmation=$EXPECTED_CONTEXT/$ARGOCD_APPLICATION/$chart_revision/$image_revision/$digest
  confirm_exact "$confirmation" "Synchronize only child Application '$ARGOCD_APPLICATION'."
  argocd app sync "$ARGOCD_APPLICATION" --core --revision "$chart_revision" --prune=false
}

uninstall_gitops() {
  require_lab_runtime
  if argo_owns_application || kubectl_lab get application.argoproj.io "$ARGOCD_ROOT_APPLICATION" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    die 'A repository-owned Argo Application exists. Follow the documented orphan-and-reversal procedure before uninstalling Argo CD.'
  fi
  confirm_exact "$ARGOCD_RELEASE" "Remove only Argo CD release '$ARGOCD_RELEASE'. CRDs and application workloads are preserved."
  helm uninstall "$ARGOCD_RELEASE" --kube-context "$EXPECTED_CONTEXT" --namespace "$ARGOCD_NAMESPACE" --wait
}

usage() {
  printf 'usage: %s {install|bootstrap|status|root-status|root-diff|root-sync|app-status|app-diff|app-sync|validate|uninstall}\n' "$0" >&2
  exit 2
}

case ${1:-} in
  install) install_gitops ;;
  bootstrap) bootstrap_gitops ;;
  status) status_gitops ;;
  root-status) root_status ;;
  root-diff) root_diff ;;
  root-sync) root_sync ;;
  app-status) app_status ;;
  app-diff) app_diff ;;
  app-sync) app_sync ;;
  validate) "$SCRIPT_DIR/validate-gitops.sh" ;;
  uninstall) uninstall_gitops ;;
  *) usage ;;
esac
