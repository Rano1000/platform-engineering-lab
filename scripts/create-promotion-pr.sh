#!/bin/sh
set -eu

REPOSITORY_ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
APPLICATION=$REPOSITORY_ROOT/environments/local/gitops/applications/golden-path-api.yaml
TEMPLATE=$APPLICATION.tmpl
EVIDENCE=$REPOSITORY_ROOT/environments/local/gitops/evidence/golden-path-api.json

die() { printf 'ERROR %s\n' "$*" >&2; exit 1; }

[ "$#" -eq 1 ] || die "usage: $0 EVIDENCE_JSON"
candidate=$1
command -v gh >/dev/null 2>&1 || die 'the pinned GitHub CLI must be on PATH'
[ "${GITHUB_REPOSITORY:-}" = Rano1000/platform-engineering-lab ] || die 'unexpected GitHub repository'
[ -n "${GITHUB_TOKEN:-}" ] || die 'GITHUB_TOKEN is required'

image_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageSourceRevision"])' "$candidate")
chart_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["chartRevision"])' "$candidate")
digest=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageDigest"])' "$candidate")
case $image_revision in
  *[!0-9a-f]*|'') die 'image source revision must be a complete lowercase Git SHA' ;;
esac
[ "${#image_revision}" -eq 40 ] || die 'image source revision must contain 40 characters'
printf '%s\n' "$chart_revision" | grep -Eq '^[0-9a-f]{40}$' || die 'chart revision must be a complete lowercase Git SHA'
printf '%s\n' "$digest" | grep -Eq '^sha256:[0-9a-f]{64}$' || die 'image digest must be complete and immutable'
branch=promotion/golden-path-api-$(printf '%s' "$image_revision" | cut -c1-12)

existing=$(gh pr list --repo "$GITHUB_REPOSITORY" --state open --json title,headRefName --limit 100)
pr_state=$(python3 - "$existing" "$branch" "$digest" <<'PY'
import json, sys
prs = json.loads(sys.argv[1])
branch, digest = sys.argv[2:]
for pr in prs:
    if pr["title"].startswith("promote: golden-path") and pr["headRefName"] != branch:
        raise SystemExit(f"another promotion PR is open: {pr['title']}")
    if pr["headRefName"] == branch:
        if digest in pr["title"]:
            print("same")
            break
        raise SystemExit("promotion branch is already associated with unrelated content")
else:
    print("none")
PY
)
[ "$pr_state" = none ] || { printf '%s\n' 'Promotion PR already exists for this source revision and digest.'; exit 0; }

if git -C "$REPOSITORY_ROOT" ls-remote --exit-code --heads origin "refs/heads/$branch" >/dev/null 2>&1; then
  die "remote branch '$branch' exists without a matching open promotion PR; refusing to overwrite it"
fi

git -C "$REPOSITORY_ROOT" switch --create "$branch"
python3 - "$TEMPLATE" "$candidate" "$APPLICATION" <<'PY'
import json, pathlib, sys
template, evidence_path, output = map(pathlib.Path, sys.argv[1:])
evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
rendered = template.read_text(encoding="utf-8")
rendered = rendered.replace("${CHART_REVISION}", evidence["chartRevision"])
rendered = rendered.replace("${IMAGE_SOURCE_REVISION}", evidence["imageSourceRevision"])
rendered = rendered.replace("${IMAGE_DIGEST}", evidence["imageDigest"])
output.write_text(rendered, encoding="utf-8")
PY
cp "$candidate" "$EVIDENCE"
python3 "$REPOSITORY_ROOT/scripts/validate-promotion.py" --evidence "$EVIDENCE" --application "$APPLICATION"

changed=$(git -C "$REPOSITORY_ROOT" status --short | awk '{print $2}' | sort)
expected=$(printf '%s\n' environments/local/gitops/applications/golden-path-api.yaml environments/local/gitops/evidence/golden-path-api.json | sort)
[ "$changed" = "$expected" ] || die "promotion attempted unexpected file changes:\n$changed"
git -C "$REPOSITORY_ROOT" add -- "$APPLICATION" "$EVIDENCE"
git -C "$REPOSITORY_ROOT" config user.name 'github-actions[bot]'
git -C "$REPOSITORY_ROOT" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$REPOSITORY_ROOT" commit -m "chore: promote golden-path-api $(printf '%s' "$digest" | cut -c1-19)" -m "Image-Source: $image_revision"
git -C "$REPOSITORY_ROOT" push origin "HEAD:refs/heads/$branch"

body=$(python3 - "$candidate" <<'PY'
import json, sys
e = json.load(open(sys.argv[1]))
v, s = e["vulnerabilities"], e["scanner"]
print(f"""## Verified image promotion

- Chart revision: `{e['chartRevision']}`
- Image source revision: `{e['imageSourceRevision']}`
- Image: `{e['image']}@{e['imageDigest']}`
- OCI revision: `{e['ociRevision']}`
- Archive SHA-256: `{e['archiveSha256']}`
- SBOM SHA-256: `{e['sbomSha256']}`
- Vulnerability report SHA-256: `{e['vulnerabilityReportSha256']}`
- Attestations: archive, SBOM, and image verified
- Vulnerabilities: `{v['severityTotals']}`
- Fixable HIGH/CRITICAL: `{v['fixableHigh']}/{v['fixableCritical']}`
- Trivy: `{s['version']}`
- Database updated: `{s['databaseUpdatedAt']}`

This PR never merges itself. Because it is created with `GITHUB_TOKEN`, a repository writer must manually start or approve the required PR validation workflows.
""")
PY
)
gh pr create --repo "$GITHUB_REPOSITORY" --base main --head "$branch" \
  --title "promote: golden-path-api@$digest" --body "$body"
