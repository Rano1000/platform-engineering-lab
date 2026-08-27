#!/bin/sh
set -eu

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
revision=0123456789abcdef0123456789abcdef01234567
tag=0.1.0-0123456789ab
digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

python3 - "$temporary" "$revision" "$digest" <<'PY'
import json, pathlib, sys
destination, revision, digest = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
template = pathlib.Path("environments/local/gitops/applications/golden-path-api.yaml.tmpl").read_text(encoding="utf-8")
application = template.replace("${CHART_REVISION}", revision).replace("${IMAGE_SOURCE_REVISION}", revision).replace("${IMAGE_DIGEST}", digest)
(destination / "child-application.yaml").write_text(application, encoding="utf-8")
evidence = {
    "schemaVersion": 2, "chartRevision": revision, "imageSourceRevision": revision,
    "image": "ghcr.io/rano1000/golden-path-api", "imageDigest": digest, "ociRevision": revision,
    "archiveSha256": "b" * 64, "sbomSha256": "c" * 64, "vulnerabilityReportSha256": "d" * 64,
    "attestations": {
        "repository": "Rano1000/platform-engineering-lab", "owner": "Rano1000",
        "archive": "verified", "sbom": "verified", "image": "verified",
        "subjects": {"archive": "sha256:" + "b" * 64, "sbom": "sha256:" + "c" * 64, "image": digest},
    },
    "vulnerabilities": {"severityTotals": {"CRITICAL": 5, "HIGH": 31}, "fixableHigh": 0, "fixableCritical": 0},
    "scanner": {"name": "Trivy", "version": "0.74.0", "databaseUpdatedAt": "2026-08-27T00:00:00Z"},
    "publication": {"visibility": "public", "repositoryLinked": True},
}
(destination / "promotion-evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
PY

python3 scripts/detect-image-impact.py --self-test
python3 scripts/validate-promotion.py --self-test
python3 scripts/update-chart-promotion.py --self-test
python3 scripts/validate-reconciliation.py --self-test
python3 scripts/validate-promotion.py --evidence "$temporary/promotion-evidence.json" \
  --application "$temporary/child-application.yaml"
./scripts/verify-promotion-artifacts.sh self-test
./scripts/publish-image.sh self-test
python3 scripts/validate-publication.py self-test

helm lint charts/golden-path-api --kube-version 1.35.0 \
  --set-string "image.tag=$tag" --set-string "image.revision=$revision" >/dev/null
helm template golden-path charts/golden-path-api --namespace platform-apps --kube-version 1.35.0 \
  --set-string "image.tag=$tag" --set-string "image.revision=$revision" >"$temporary/local.yaml"
helm lint charts/golden-path-api --kube-version 1.35.0 \
  --set-string image.repository=ghcr.io/rano1000/golden-path-api --set-string image.tag= \
  --set-string "image.digest=$digest" --set-string "image.revision=$revision" \
  --set-string image.pullPolicy=IfNotPresent >/dev/null
helm template golden-path charts/golden-path-api --namespace platform-apps --kube-version 1.35.0 \
  --set-string image.repository=ghcr.io/rano1000/golden-path-api --set-string image.tag= \
  --set-string "image.digest=$digest" --set-string "image.revision=$revision" \
  --set-string image.pullPolicy=IfNotPresent >"$temporary/gitops.yaml"
./scripts/render-argocd.sh "$temporary/argocd.yaml"
python3 scripts/validate-phase4.py --local-render "$temporary/local.yaml" \
  --gitops-render "$temporary/gitops.yaml" --argocd-render "$temporary/argocd.yaml"

if command -v kubeconform >/dev/null 2>&1; then
  kubeconform -kubernetes-version 1.35.0 -strict -ignore-missing-schemas -summary \
    "$temporary/local.yaml" "$temporary/gitops.yaml" "$temporary/argocd.yaml"
else
  printf '%s\n' 'WARN  kubeconform is unavailable; rendering and semantic validation passed.'
fi
