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

harden_default_project() (
  gitops_project_tmp=$(mktemp -d)
  trap 'rm -rf "$gitops_project_tmp"' EXIT HUP INT TERM
  gitops_project_validator=$SCRIPT_DIR/validate-default-appproject.py
  kubectl_lab get appproject default --namespace "$ARGOCD_NAMESPACE" --show-managed-fields=true \
    -o json >"$gitops_project_tmp/live-a.json"
  kubectl_lab get applications.argoproj.io --all-namespaces -o json >"$gitops_project_tmp/applications-a.json"
  python3 "$gitops_project_validator" preflight --desired "$ARGOCD_DEFAULT_PROJECT" \
    --live "$gitops_project_tmp/live-a.json" --applications "$gitops_project_tmp/applications-a.json" \
    --output "$gitops_project_tmp/record.json"
  gitops_project_state=$(python3 "$gitops_project_validator" field --record "$gitops_project_tmp/record.json" --name state)
  if [ "$gitops_project_state" = hardened ]; then
    gitops_project_checksum=$(python3 "$gitops_project_validator" validate-live \
      --desired "$ARGOCD_DEFAULT_PROJECT" --live "$gitops_project_tmp/live-a.json")
    printf 'PASS  default AppProject is already repository-owned and deny-all (%s); no transfer was forced.\n' \
      "$gitops_project_checksum"
    exit 0
  fi
  kubectl_lab apply --server-side --force-conflicts --dry-run=server \
    --field-manager="$ARGOCD_DEFAULT_PROJECT_FIELD_MANAGER" -f "$ARGOCD_DEFAULT_PROJECT" -o json \
    >"$gitops_project_tmp/dry-run.json"
  python3 "$gitops_project_validator" validate-dry-run --record "$gitops_project_tmp/record.json" \
    --live "$gitops_project_tmp/live-a.json" --dry-run "$gitops_project_tmp/dry-run.json" \
    --desired "$ARGOCD_DEFAULT_PROJECT"
  kubectl_lab get appproject default --namespace "$ARGOCD_NAMESPACE" --show-managed-fields=true \
    -o json >"$gitops_project_tmp/live-b.json"
  kubectl_lab get applications.argoproj.io --all-namespaces -o json >"$gitops_project_tmp/applications-b.json"
  python3 "$gitops_project_validator" verify-unchanged --record "$gitops_project_tmp/record.json" \
    --live "$gitops_project_tmp/live-b.json" --applications "$gitops_project_tmp/applications-b.json"
  gitops_project_confirmation=$(python3 "$gitops_project_validator" confirmation \
    --record "$gitops_project_tmp/record.json")
  confirm_exact "$gitops_project_confirmation" \
    "Transfer only the reviewed fields of gitops/AppProject default from argocd-server to $ARGOCD_DEFAULT_PROJECT_FIELD_MANAGER."
  kubectl_lab get appproject default --namespace "$ARGOCD_NAMESPACE" --show-managed-fields=true \
    -o json >"$gitops_project_tmp/live-c.json"
  kubectl_lab get applications.argoproj.io --all-namespaces -o json >"$gitops_project_tmp/applications-c.json"
  python3 "$gitops_project_validator" verify-unchanged --record "$gitops_project_tmp/record.json" \
    --live "$gitops_project_tmp/live-c.json" --applications "$gitops_project_tmp/applications-c.json"
  kubectl_lab apply --server-side --force-conflicts --field-manager="$ARGOCD_DEFAULT_PROJECT_FIELD_MANAGER" \
    -f "$ARGOCD_DEFAULT_PROJECT"
  kubectl_lab get appproject default --namespace "$ARGOCD_NAMESPACE" --show-managed-fields=true \
    -o json >"$gitops_project_tmp/live-after.json"
  gitops_project_checksum=$(python3 "$gitops_project_validator" validate-post \
    --record "$gitops_project_tmp/record.json" --desired "$ARGOCD_DEFAULT_PROJECT" \
    --live "$gitops_project_tmp/live-after.json")
  [ "$gitops_project_checksum" = "$ARGOCD_DEFAULT_PROJECT_SHA256" ] ||
    die "Default AppProject checksum mismatch: $gitops_project_checksum."
  sleep "$ARGOCD_DEFAULT_PROJECT_STABILIZATION_SECONDS"
  kubectl_lab get appproject default --namespace "$ARGOCD_NAMESPACE" --show-managed-fields=true \
    -o json >"$gitops_project_tmp/live-stable.json"
  gitops_project_stable_checksum=$(python3 "$gitops_project_validator" validate-post --stabilized \
    --record "$gitops_project_tmp/record.json" --desired "$ARGOCD_DEFAULT_PROJECT" \
    --live "$gitops_project_tmp/live-stable.json")
  [ "$gitops_project_stable_checksum" = "$gitops_project_checksum" ] ||
    die 'Default AppProject changed during bounded stabilization.'
  printf 'PASS  default AppProject ownership transfer is stable and deny-all (%s).\n' "$gitops_project_checksum"
)

harden_default_project_guarded() {
  require_lab_runtime
  helm --kube-context "$EXPECTED_CONTEXT" status "$ARGOCD_RELEASE" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1 ||
    die "Argo CD release '$ARGOCD_RELEASE' is not installed."
  harden_default_project
}

install_gitops() {
  require_lab_runtime
  require_command docker
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  archive=$(verify_chart "$temporary")
  identity_checksum=$(resolve_argocd_api_endpoint "$temporary" snapshot-a)
  printf 'Verified Kubernetes API endpoint identity (%s):\n' "$identity_checksum"
  cat "$temporary/snapshot-a-identity.json"
  if kubectl_lab get networkpolicy argocd-redis-secret-init --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
    die 'Legacy ClusterIP hook policy remains from the failed installation. Obtain exact-name cleanup approval before retrying.'
  fi
  confirm_exact "$CLUSTER_NAME" "Install pinned Argo CD $ARGOCD_VERSION into '$ARGOCD_NAMESPACE' on '$EXPECTED_CONTEXT'. This creates cluster-scoped CRDs and RBAC. Verified API endpoint identity: $identity_checksum."
  kubectl_lab apply -f "$ARGOCD_CONFIG/resource-controls.yaml"
  kubectl_lab apply -f "$ARGOCD_CONFIG/network-policies.yaml"
  kubectl_lab apply -f "$temporary/snapshot-a-policies.yaml"
  verify_live_argocd_api_policies "$temporary/snapshot-a-identity.json" "$temporary/live-before.json"
  GITOPS_NETWORK_IDENTITY=$temporary/snapshot-a-identity.json GITOPS_NETWORK_NONINTERACTIVE=1 \
    "$SCRIPT_DIR/test-gitops-network.sh"
  resolve_argocd_api_endpoint "$temporary" snapshot-b >/dev/null
  compare_argocd_api_snapshots "$temporary/snapshot-a-identity.json" "$temporary/snapshot-b-identity.json"
  verify_live_argocd_api_policies "$temporary/snapshot-b-identity.json" "$temporary/live-immediately-before-helm.json"
  if helm upgrade --install "$ARGOCD_RELEASE" "$archive" --kube-context "$EXPECTED_CONTEXT" \
    --namespace "$ARGOCD_NAMESPACE" --values "$ARGOCD_CONFIG/values.yaml" \
    --atomic --wait --timeout "${ARGOCD_INSTALL_TIMEOUT_SECONDS}s"; then
    :
  else
    gitops_helm_status=$?
    gitops_failure_root=$REPOSITORY_ROOT/.artifacts/gitops-install/$(date +%s)-$$
    python3 "$SCRIPT_DIR/validate-diagnostic-path.py" ensure-dir \
      --base "$REPOSITORY_ROOT/.artifacts/gitops-install" --root "$gitops_failure_root" --path "$gitops_failure_root"
    if ! python3 "$SCRIPT_DIR/capture-gitops-install-failure.py" \
      --context "$EXPECTED_CONTEXT" --namespace "$ARGOCD_NAMESPACE" --release "$ARGOCD_RELEASE" \
      --output "$gitops_failure_root/evidence"; then
      printf 'WARN  Argo installation failed and diagnostic capture was incomplete: %s\n' "$gitops_failure_root" >&2
    fi
    return "$gitops_helm_status"
  fi
  harden_default_project
  resolve_argocd_api_endpoint "$temporary" snapshot-c >/dev/null
  compare_argocd_api_snapshots "$temporary/snapshot-b-identity.json" "$temporary/snapshot-c-identity.json"
  verify_live_argocd_api_policies "$temporary/snapshot-c-identity.json" "$temporary/live-after.json"
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
  run_guarded_argocd_diff root "$application" "$child_spec_checksum" "$temporary" \
    app diff "$ARGOCD_ROOT_APPLICATION" --revision "$environment_revision"
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
  run_guarded_argocd_diff root "$application" "$child_spec_checksum" "$temporary" \
    app diff "$ARGOCD_ROOT_APPLICATION" --revision "$environment_revision"
  require_environment_revision_current "$environment_revision"
  confirmation=$EXPECTED_CONTEXT/$ARGOCD_ROOT_APPLICATION/$environment_revision/$chart_revision/$image_revision/$digest/sha256:$child_spec_checksum
  confirm_exact "$confirmation" "Synchronize only root Application '$ARGOCD_ROOT_APPLICATION' from immutable environmentRevision '$environment_revision'."
  require_environment_revision_current "$environment_revision"
  run_argocd_core app sync "$ARGOCD_ROOT_APPLICATION" --revision "$environment_revision" --prune=false
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
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  run_guarded_argocd_diff child '' '' "$temporary" app diff "$ARGOCD_APPLICATION"
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
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  run_guarded_argocd_diff child '' '' "$temporary" app diff "$ARGOCD_APPLICATION"
  confirmation=$EXPECTED_CONTEXT/$ARGOCD_APPLICATION/$chart_revision/$image_revision/$digest
  confirm_exact "$confirmation" "Synchronize only child Application '$ARGOCD_APPLICATION'."
  run_argocd_core app sync "$ARGOCD_APPLICATION" --revision "$chart_revision" --prune=false
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
  printf 'usage: %s {install|harden-default-project|bootstrap|status|root-status|root-diff|root-sync|app-status|app-diff|app-sync|validate|uninstall}\n' "$0" >&2
  exit 2
}

case ${1:-} in
  install) install_gitops ;;
  harden-default-project) harden_default_project_guarded ;;
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
