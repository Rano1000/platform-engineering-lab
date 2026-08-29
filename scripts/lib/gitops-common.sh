#!/bin/sh

ARGOCD_VERSION=v3.5.2
ARGOCD_CHART_VERSION=10.4.0
ARGOCD_CHART=oci://ghcr.io/argoproj/argo-helm/argo-cd
ARGOCD_CHART_DIGEST=sha256:8ff18ee7a22670305555167ea31f24a88e2f912cf0a872f852e1880886d4c308
ARGOCD_CHART_ARCHIVE_SHA256=5abb71c17bc082e13dc3d90023972f871ea8e1dfc26d8f3218ceade215b971d5
ARGOCD_CHART_PROVENANCE_SHA256=a50c4cc9f68fce2aeaf611a71d158e847c5fedce27cab1e867106f177cc0bf4e
ARGOCD_SIGNING_KEY_URL=https://argoproj.github.io/argo-helm/pgp_keys.asc
ARGOCD_SIGNING_KEY_SHA256=36366596211a1587d018be5b178687799cb2edfc3e3e3c6ccd661b33fc6305ca
ARGOCD_SIGNING_KEY_FINGERPRINT=2B8F22F57260EFA67BE1C5824B11F800CD9D2252
ARGOCD_IMAGE_DIGEST=sha256:e2aadfae709d904e87f46ba4aa49601d827b3022db22cd4d03aae816a2e7097b
ARGOCD_RELEASE=argocd
ARGOCD_NAMESPACE=gitops
ARGOCD_INSTALL_TIMEOUT_SECONDS=900
ARGOCD_DEFAULT_PROJECT_SHA256=sha256:102d3a96976670f66b262eb2c45a0ad2ff30529c79844a3dd9e85f02f1b71625
ARGOCD_DEFAULT_PROJECT_FIELD_MANAGER=platform-engineering-lab-default-project
ARGOCD_DEFAULT_PROJECT_STABILIZATION_SECONDS=5
ARGOCD_APPLICATION=golden-path-api
ARGOCD_ROOT_APPLICATION=platform-environment
ARGOCD_PROJECT=platform-apps
ARGOCD_CONFIG=$REPOSITORY_ROOT/platform/addons/argocd
ARGOCD_DEFAULT_PROJECT=$ARGOCD_CONFIG/default-project.yaml
ARGOCD_ENVIRONMENT=$REPOSITORY_ROOT/environments/local/gitops
ARGOCD_API_POLICY_TEMPLATE=$ARGOCD_CONFIG/api-endpoint-policies.yaml.tpl
ARGOCD_CLI_INSTALLER=$REPOSITORY_ROOT/scripts/argocd-cli.py

resolve_argocd_api_endpoint() {
  destination=$1
  prefix=$2
  mkdir -p "$destination"
  kubectl_lab get service kubernetes --namespace default -o json >"$destination/$prefix-service.json"
  kubectl_lab get endpointslice --namespace default -l kubernetes.io/service-name=kubernetes -o json >"$destination/$prefix-endpoints.json"
  kubectl_lab get node "$CONTROL_PLANE_CONTAINER" -o json >"$destination/$prefix-node.json"
  kubectl_lab get pod "kube-apiserver-$CONTROL_PLANE_CONTAINER" --namespace kube-system -o json >"$destination/$prefix-apiserver.json"
  docker network inspect kind >"$destination/$prefix-network-list.json"
  python3 - "$destination/$prefix-network-list.json" "$destination/$prefix-network.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(value, list) or len(value) != 1:
    raise SystemExit("FAIL  exactly one kind Docker network is required")
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(value[0], stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
PY
  python3 "$REPOSITORY_ROOT/scripts/resolve-kubernetes-api.py" render \
    --service "$destination/$prefix-service.json" --endpoints "$destination/$prefix-endpoints.json" \
    --node "$destination/$prefix-node.json" --apiserver "$destination/$prefix-apiserver.json" \
    --network "$destination/$prefix-network.json" --template "$ARGOCD_API_POLICY_TEMPLATE" \
    --context "$EXPECTED_CONTEXT" --cluster "$CLUSTER_NAME" \
    --identity-output "$destination/$prefix-identity.json" --policy-output "$destination/$prefix-policies.yaml"
}

compare_argocd_api_snapshots() {
  python3 "$REPOSITORY_ROOT/scripts/resolve-kubernetes-api.py" compare --expected "$1" --actual "$2"
}

verify_live_argocd_api_policies() {
  identity=$1
  output=$2
  kubectl_lab get networkpolicy argocd-redis-secret-init-api argocd-application-controller-api \
    argocd-server-api --namespace "$ARGOCD_NAMESPACE" -o json >"$output"
  python3 "$REPOSITORY_ROOT/scripts/resolve-kubernetes-api.py" verify-live --identity "$identity" --policies "$output"
}

verify_argocd_chart() {
  destination=$1
  require_command curl
  require_command gpg
  require_command helm
  key=$destination/argo-helm-signing-key.asc
  keyring=$destination/argo-helm-signing-key.gpg
  pull_log=$destination/helm-pull.log
  curl -fsSL "$ARGOCD_SIGNING_KEY_URL" -o "$key"
  actual_key_sha=$(sha256sum "$key" | awk '{print $1}')
  [ "$actual_key_sha" = "$ARGOCD_SIGNING_KEY_SHA256" ] || die "Argo Helm signing-key checksum mismatch: $actual_key_sha."
  mkdir -m 0700 "$destination/gpg-home"
  fingerprint=$(GNUPGHOME=$destination/gpg-home gpg --show-keys --with-colons "$key" 2>/dev/null |
    awk -F: '$1 == "fpr" {print $10; exit}')
  [ "$fingerprint" = "$ARGOCD_SIGNING_KEY_FINGERPRINT" ] || die "Unexpected Argo Helm signing-key fingerprint: ${fingerprint:-missing}."
  GNUPGHOME=$destination/gpg-home gpg --batch --dearmor --output "$keyring" "$key"
  helm pull "$ARGOCD_CHART" --version "$ARGOCD_CHART_VERSION" --prov \
    --destination "$destination" >"$pull_log" 2>&1
  grep -F "Digest: $ARGOCD_CHART_DIGEST" "$pull_log" >/dev/null ||
    die 'Argo CD OCI chart manifest digest did not match the approved digest.'
  archive=$destination/argo-cd-$ARGOCD_CHART_VERSION.tgz
  provenance=$archive.prov
  actual=$(sha256sum "$archive" | awk '{print $1}')
  [ "$actual" = "$ARGOCD_CHART_ARCHIVE_SHA256" ] || die "Argo CD chart checksum mismatch: $actual."
  actual_provenance=$(sha256sum "$provenance" | awk '{print $1}')
  [ "$actual_provenance" = "$ARGOCD_CHART_PROVENANCE_SHA256" ] ||
    die "Argo CD chart provenance checksum mismatch: $actual_provenance."
  helm verify "$archive" --keyring "$keyring" >/dev/null
  app_version=$(helm show chart "$archive" | awk '$1 == "appVersion:" {print $2}')
  [ "$app_version" = v3.5.1 ] || die "Chart appVersion changed from reviewed v3.5.1 to $app_version."
  printf '%s\n' "$archive"
}

require_argocd_application() {
  kubectl_lab get application.argoproj.io "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1 ||
    die "Argo Application '$ARGOCD_APPLICATION' is not installed."
}

require_argocd_root_application() {
  kubectl_lab get application.argoproj.io "$ARGOCD_ROOT_APPLICATION" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1 ||
    die "Root Argo Application '$ARGOCD_ROOT_APPLICATION' is not installed."
}

argo_owns_application() {
  kubectl_lab get application.argoproj.io "$ARGOCD_APPLICATION" --namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1
}

require_argocd_cli() {
  repository_cli=$(python3 "$ARGOCD_CLI_INSTALLER" path) || die 'Unable to resolve the repository-local Argo CD CLI path.'
  if [ -e "$repository_cli" ] || [ -L "$repository_cli" ]; then
    ARGOCD_CLI=$(python3 "$ARGOCD_CLI_INSTALLER" verify) ||
      die "Repository-local Argo CD CLI failed verification. Run 'make gitops-cli-install'."
  elif command -v argocd >/dev/null 2>&1; then
    ARGOCD_CLI=$(command -v argocd)
    version=$("$ARGOCD_CLI" version --client --short 2>/dev/null | awk '{print $2}' | head -1)
    version=${version%%+*}
    [ "$version" = "$ARGOCD_VERSION" ] || die "argocd CLI must be exactly $ARGOCD_VERSION; found ${version:-unknown}."
  else
    die "Argo CD CLI $ARGOCD_VERSION is unavailable. Run 'make gitops-cli-install'."
  fi
  export ARGOCD_CLI
}

require_clean_synchronized_repository() {
  [ -z "$(git -C "$REPOSITORY_ROOT" status --porcelain --untracked-files=normal)" ] ||
    die 'The repository must be clean before synchronization.'
  [ "$(git -C "$REPOSITORY_ROOT" branch --show-current)" = main ] || die 'Synchronization requires the local main branch.'
  git -C "$REPOSITORY_ROOT" fetch --quiet origin refs/heads/main:refs/remotes/origin/main
  environment_revision=$(git -C "$REPOSITORY_ROOT" rev-parse refs/remotes/origin/main)
  local_head=$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)
  printf '%s\n' "$environment_revision" | grep -Eq '^[0-9a-f]{40}$' || die 'origin/main did not resolve to a complete immutable commit SHA.'
  [ "$local_head" = "$environment_revision" ] || die "Local HEAD $local_head differs from origin/main $environment_revision."
  git -C "$REPOSITORY_ROOT" merge-base --is-ancestor "$environment_revision" refs/remotes/origin/main ||
    die 'environmentRevision is not an ancestor of origin/main.'
}

require_environment_revision_current() {
  expected=$1
  printf '%s\n' "$expected" | grep -Eq '^[0-9a-f]{40}$' || die 'environmentRevision must be a complete immutable commit SHA.'
  git -C "$REPOSITORY_ROOT" fetch --quiet origin refs/heads/main:refs/remotes/origin/main
  current=$(git -C "$REPOSITORY_ROOT" rev-parse refs/remotes/origin/main)
  [ "$current" = "$expected" ] || die "origin/main changed from reviewed environmentRevision $expected to $current."
  git -C "$REPOSITORY_ROOT" merge-base --is-ancestor "$expected" refs/remotes/origin/main ||
    die 'Reviewed environmentRevision is no longer an ancestor of origin/main.'
}
