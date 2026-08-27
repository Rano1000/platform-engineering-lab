#!/bin/sh
set -eu

REPOSITORY_ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
APPLICATION=$REPOSITORY_ROOT/environments/local/gitops/applications/golden-path-api.yaml
EVIDENCE=$REPOSITORY_ROOT/environments/local/gitops/evidence/golden-path-api.json
CHART=$REPOSITORY_ROOT/charts/golden-path-api
EXPECTED_REPOSITORY=Rano1000/platform-engineering-lab

die() { printf 'ERROR %s\n' "$*" >&2; exit 1; }

[ "${GITHUB_REPOSITORY:-}" = "$EXPECTED_REPOSITORY" ] || die 'unexpected GitHub repository'
[ "${GITHUB_EVENT_NAME:-}" = push ] && [ "${GITHUB_REF:-}" = refs/heads/main ] || die 'chart promotion is restricted to main pushes'
[ -n "${GITHUB_TOKEN:-}" ] || die 'GITHUB_TOKEN is required'
command -v gh >/dev/null 2>&1 || die 'the pinned GitHub CLI must be on PATH'
command -v helm >/dev/null 2>&1 || die 'Helm is required'
[ -f "$APPLICATION" ] || die 'no approved child Application exists; complete the first image promotion first'
python3 "$REPOSITORY_ROOT/scripts/validate-promotion.py" --evidence "$EVIDENCE" --application "$APPLICATION"

chart_revision=${GITHUB_SHA:-}
printf '%s\n' "$chart_revision" | grep -Eq '^[0-9a-f]{40}$' || die 'chart revision must be a complete lowercase Git SHA'
image_digest=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageDigest"])' "$EVIDENCE")
image_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["imageSourceRevision"])' "$EVIDENCE")
current_chart_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["chartRevision"])' "$EVIDENCE")
[ "$current_chart_revision" != "$chart_revision" ] || die 'chart revision is already approved'
rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT HUP INT TERM
helm lint "$CHART" --kube-version 1.35.0 \
  --set-string image.repository=ghcr.io/rano1000/golden-path-api --set-string image.tag= \
  --set-string "image.digest=$image_digest" --set-string "image.revision=$image_revision" \
  --set-string image.pullPolicy=IfNotPresent >/dev/null
helm template golden-path "$CHART" --namespace platform-apps --kube-version 1.35.0 \
  --set-string image.repository=ghcr.io/rano1000/golden-path-api --set-string image.tag= \
  --set-string "image.digest=$image_digest" --set-string "image.revision=$image_revision" \
  --set-string image.pullPolicy=IfNotPresent >"$rendered"
grep -F "image: \"ghcr.io/rano1000/golden-path-api@$image_digest\"" "$rendered" >/dev/null ||
  die 'rendered chart does not use the currently approved immutable image digest'

branch=promotion/golden-path-chart-$(printf '%s' "$chart_revision" | cut -c1-12)
existing=$(gh pr list --repo "$GITHUB_REPOSITORY" --state open --json title,headRefName --limit 100)
pr_state=$(python3 - "$existing" "$branch" <<'PY'
import json, sys
prs, branch = json.loads(sys.argv[1]), sys.argv[2]
for pr in prs:
    if pr["title"].startswith("promote: golden-path") and pr["headRefName"] != branch:
        raise SystemExit(f"another promotion PR is open: {pr['title']}")
    if pr["headRefName"] == branch:
        print("same")
        break
else:
    print("none")
PY
)
[ "$pr_state" = none ] || { printf '%s\n' 'Chart promotion PR already exists for this revision.'; exit 0; }
if git -C "$REPOSITORY_ROOT" ls-remote --exit-code --heads origin "refs/heads/$branch" >/dev/null 2>&1; then
  die "remote branch '$branch' exists without a matching open promotion PR; refusing to overwrite it"
fi

git -C "$REPOSITORY_ROOT" switch --create "$branch"
python3 "$REPOSITORY_ROOT/scripts/update-chart-promotion.py" \
  --application "$APPLICATION" --evidence "$EVIDENCE" --chart-revision "$chart_revision"
python3 "$REPOSITORY_ROOT/scripts/validate-promotion.py" --evidence "$EVIDENCE" --application "$APPLICATION"
changed=$(git -C "$REPOSITORY_ROOT" status --short | awk '{print $2}' | sort)
expected=$(printf '%s\n' environments/local/gitops/applications/golden-path-api.yaml environments/local/gitops/evidence/golden-path-api.json | sort)
[ "$changed" = "$expected" ] || die "chart promotion attempted unexpected file changes:\n$changed"
git -C "$REPOSITORY_ROOT" add -- "$APPLICATION" "$EVIDENCE"
git -C "$REPOSITORY_ROOT" config user.name 'github-actions[bot]'
git -C "$REPOSITORY_ROOT" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$REPOSITORY_ROOT" commit -m "chore: promote golden-path chart $(printf '%s' "$chart_revision" | cut -c1-12)"
git -C "$REPOSITORY_ROOT" push origin "HEAD:refs/heads/$branch"
body=$(printf '%s\n' \
  '## Verified chart promotion' '' \
  "- Chart revision: \`$chart_revision\`" \
  "- Preserved image source revision: \`$image_revision\`" \
  "- Preserved image: \`ghcr.io/rano1000/golden-path-api@$image_digest\`" '' \
  'No image was built or published. This PR never merges itself and changes only chart revision metadata.')
gh pr create --repo "$GITHUB_REPOSITORY" --base main --head "$branch" \
  --title "promote: golden-path chart@$chart_revision" --body "$body"
