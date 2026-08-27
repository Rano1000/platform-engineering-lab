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
ARGOCD_APPLICATION=golden-path-api
ARGOCD_ROOT_APPLICATION=platform-environment
ARGOCD_PROJECT=platform-apps
ARGOCD_CONFIG=$REPOSITORY_ROOT/platform/addons/argocd
ARGOCD_ENVIRONMENT=$REPOSITORY_ROOT/environments/local/gitops

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
  require_command argocd
  version=$(argocd version --client --short 2>/dev/null | awk '{print $2}' | head -1)
  [ "$version" = "$ARGOCD_VERSION" ] || die "argocd CLI must be exactly $ARGOCD_VERSION; found ${version:-unknown}."
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
