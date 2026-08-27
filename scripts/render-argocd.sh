#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/cluster-common.sh
. "$SCRIPT_DIR/lib/cluster-common.sh"
# shellcheck source=SCRIPTDIR/lib/gitops-common.sh
. "$SCRIPT_DIR/lib/gitops-common.sh"

[ "$#" -eq 1 ] || { printf 'usage: %s OUTPUT\n' "$0" >&2; exit 2; }
output=$1
require_command helm
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
archive=$(verify_argocd_chart "$temporary")
app_version=$(helm show chart "$archive" | awk '$1 == "appVersion:" {print $2}')
helm template "$ARGOCD_RELEASE" "$archive" --namespace "$ARGOCD_NAMESPACE" --include-crds \
  --kube-version 1.35.0 --values "$ARGOCD_CONFIG/values.yaml" >"$output"
printf 'PASS  verified and rendered Argo CD chart %s (declared appVersion %s) with the reviewed %s override.\n' \
  "$ARGOCD_CHART_VERSION" "$app_version" "$ARGOCD_VERSION"
