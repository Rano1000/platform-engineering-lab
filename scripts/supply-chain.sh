#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/lib/supply-chain-common.sh
. "$SCRIPT_DIR/lib/supply-chain-common.sh"

verify_clean_revision() {
  [ -z "$(git -C "$PROJECT_ROOT" status --porcelain --untracked-files=normal)" ] ||
    die 'Refusing to label uncommitted source with a Git revision.'
  revision=$(full_revision)
  case "$revision" in
    *[!0-9a-f]*|'') die 'Git revision must be a complete lowercase hexadecimal SHA.' ;;
  esac
  [ "${#revision}" -eq 40 ] || die 'Git revision must contain exactly 40 characters.'
  if [ -n "${GITHUB_SHA:-}" ] && [ "$revision" != "$GITHUB_SHA" ]; then
    die 'Checked-out revision does not match GITHUB_SHA.'
  fi
}

build_artifact() {
  require_command docker
  require_command sha256sum
  verify_clean_revision
  reference=$(image_reference)
  if docker image inspect "$reference" >/dev/null 2>&1; then
    die "Image '$reference' already exists; refusing to overwrite an immutable tag."
  fi
  docker build --target runtime \
    --build-arg "APP_VERSION=$APP_VERSION" \
    --build-arg "VCS_REF=$(full_revision)" \
    --tag "$reference" "$PROJECT_ROOT/applications/golden-path-api"
  prepare_artifacts
  docker image save --output "$IMAGE_ARCHIVE" "$reference"
  (cd "$ARTIFACT_DIR" && sha256sum "$(basename "$IMAGE_ARCHIVE")" >"$(basename "$IMAGE_CHECKSUM")")
  inspect_image
}

load_artifact() {
  require_command docker
  require_command sha256sum
  [ -f "$IMAGE_ARCHIVE" ] || die "Image archive '$IMAGE_ARCHIVE' is missing."
  [ -f "$IMAGE_CHECKSUM" ] || die "Checksum '$IMAGE_CHECKSUM' is missing."
  (cd "$ARTIFACT_DIR" && sha256sum --check "$(basename "$IMAGE_CHECKSUM")")
  docker image load --input "$IMAGE_ARCHIVE" >/dev/null
}

inspect_image() {
  require_command docker
  reference=$(image_reference)
  docker image inspect "$reference" >/dev/null 2>&1 || die "Image '$reference' is unavailable."
  revision=$(docker image inspect "$reference" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  user=$(docker image inspect "$reference" --format '{{.Config.User}}')
  health=$(docker image inspect "$reference" --format '{{json .Config.Healthcheck.Test}}')
  [ "$revision" = "$(full_revision)" ] || die 'OCI revision does not match the complete Git SHA.'
  [ "$user" = '10001:10001' ] || die "Runtime user is '$user', expected 10001:10001."
  [ "$health" != 'null' ] && [ "$health" != '[]' ] || die 'Runtime image has no health check.'
  if docker image inspect "$APP_IMAGE:latest" >/dev/null 2>&1; then
    die "Forbidden mutable tag '$APP_IMAGE:latest' exists locally."
  fi
  credential_pattern='(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9_]{20,}|password[=]|token[=])'
  if docker image inspect "$reference" | grep -Eiq "$credential_pattern"; then
    die 'Image configuration contains a potential credential.'
  fi
  if docker image history --no-trunc "$reference" | grep -Eiq "$credential_pattern"; then
    die 'Image history contains a potential credential.'
  fi
  docker run --rm --entrypoint /bin/sh "$reference" -c '
    set -eu
    for command in pip pytest gcc make; do
      if command -v "$command" >/dev/null 2>&1; then
        echo "unexpected runtime command: $command" >&2
        exit 1
      fi
    done
    for path in /app/tests /build /root/.cache /tmp/pip-build-tracker; do
      if [ -e "$path" ]; then
        echo "unexpected runtime path: $path" >&2
        exit 1
      fi
    done
  '
  printf 'PASS  image contract: %s, revision %s, user %s\n' "$reference" "$revision" "$user"
}

validate_policy() {
  python3 "$SCRIPT_DIR/validate-vulnerability-policy.py" "$POLICY"
}

policy_tests() {
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  valid=$temporary/valid.json
  expired=$temporary/expired.json
  broad=$temporary/broad.json
  malformed=$temporary/malformed.json
  printf '%s\n' '{"schemaVersion":1,"exceptions":[{"id":"CVE-2026-1234","reason":"Tracked upstream defect","owner":"@Rano1000","created":"2026-08-01","expires":"2026-09-01"}]}' >"$valid"
  printf '%s\n' '{"schemaVersion":1,"exceptions":[{"id":"CVE-2026-1234","reason":"Tracked upstream defect","owner":"@Rano1000","created":"2026-01-01","expires":"2026-02-01"}]}' >"$expired"
  printf '%s\n' '{"schemaVersion":1,"exceptions":[{"id":"CVE-*","reason":"Too broad","owner":"@Rano1000","created":"2026-08-01","expires":"2026-09-01"}]}' >"$broad"
  printf '%s\n' '{"schemaVersion":1,"exceptions":[{"id":"CVE-2026-1234"}]}' >"$malformed"
  python3 "$SCRIPT_DIR/validate-vulnerability-policy.py" "$valid" 2026-08-15
  if python3 "$SCRIPT_DIR/validate-vulnerability-policy.py" "$expired" 2026-08-15 >/dev/null 2>&1; then
    die 'Expired exception was accepted.'
  fi
  if python3 "$SCRIPT_DIR/validate-vulnerability-policy.py" "$broad" 2026-08-15 >/dev/null 2>&1; then
    die 'Overly broad exception was accepted.'
  fi
  if python3 "$SCRIPT_DIR/validate-vulnerability-policy.py" "$malformed" 2026-08-15 >/dev/null 2>&1; then
    die 'Malformed exception was accepted.'
  fi
  printf '%s\n' 'PASS  vulnerability policy accepts valid entries and rejects expired, broad, or malformed entries.'
}

ignore_file() {
  python3 - "$POLICY" <<'PY'
import json, sys
for item in json.load(open(sys.argv[1], encoding="utf-8"))["exceptions"]:
    print(item["id"])
PY
}

secret_scan() {
  run_trivy filesystem --scanners secret --exit-code 1 --no-progress /workspace
}

generate_sbom() {
  validate_policy
  reference=$(image_reference)
  run_trivy image --format cyclonedx --output /artifacts/golden-path-api.cdx.json --no-progress "$reference"
  (cd "$ARTIFACT_DIR" && sha256sum "$(basename "$SBOM")" >"$(basename "$SBOM").sha256")
  python3 - "$SBOM" "$SBOM_METADATA" "$reference" "$(full_revision)" "$TRIVY_VERSION" <<'PY'
import hashlib, json, pathlib, sys
sbom = pathlib.Path(sys.argv[1])
document = json.loads(sbom.read_text(encoding="utf-8"))
if document.get("bomFormat") != "CycloneDX" or not document.get("components"):
    raise SystemExit("SBOM is not a populated CycloneDX document")
summary = {
    "artifactSha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
    "image": sys.argv[3],
    "revision": sys.argv[4],
    "scanner": f"Trivy {sys.argv[5]}",
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
PY
  printf 'PASS  CycloneDX SBOM generated at %s\n' "$SBOM"
}

scan_image() {
  validate_policy
  prepare_artifacts
  reference=$(image_reference)
  ignore=$ARTIFACT_DIR/trivy-ignore.txt
  ignore_file >"$ignore"
  run_trivy image --scanners vuln --format json --output /artifacts/trivy-vulnerabilities.json --no-progress "$reference"
  record_trivy_metadata
  run_trivy image --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 \
    --ignorefile /artifacts/trivy-ignore.txt --no-progress --scanners vuln "$reference"
  python3 - "$SCAN_REPORT" "$TRIVY_METADATA" "$SCAN_SUMMARY" "$reference" "$(full_revision)" <<'PY'
import collections, json, pathlib, sys

report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
metadata = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
findings = [
    finding
    for result in report.get("Results", [])
    for finding in (result.get("Vulnerabilities") or [])
]
severity = collections.Counter(finding.get("Severity", "UNKNOWN") for finding in findings)
fixability = collections.Counter(
    "fixable" if finding.get("FixedVersion") else "unfixed" for finding in findings
)
summary = {
    "database": metadata.get("VulnerabilityDB", {}),
    "findingsByFixAvailability": dict(sorted(fixability.items())),
    "findingsBySeverity": dict(sorted(severity.items())),
    "image": sys.argv[4],
    "revision": sys.argv[5],
    "scanner": {"name": "Trivy", "version": metadata.get("Version")},
    "totalFindings": len(findings),
}
pathlib.Path(sys.argv[3]).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
PY
  printf '%s\n' 'PASS  no unexcepted fixable HIGH or CRITICAL vulnerabilities found.'
}

verify_locks() {
  for file in "$PROJECT_ROOT/applications/golden-path-api/requirements/runtime.txt" "$PROJECT_ROOT/applications/golden-path-api/requirements/test.txt"; do
    grep -q -- '--hash=sha256:' "$file" || die "Dependency lock '$file' contains no hashes."
  done
  grep -q -- '--require-hashes' "$PROJECT_ROOT/applications/golden-path-api/Dockerfile" ||
    die 'Dockerfile does not enforce dependency hashes.'
  grep -q -- '--hash=sha256:' "$PROJECT_ROOT/tools/dependency-lock/requirements.txt" ||
    die 'Dependency compiler lock contains no hashes.'
  grep -q -- '--require-hashes' "$PROJECT_ROOT/tools/dependency-lock/Dockerfile" ||
    die 'Dependency compiler does not enforce its own hashes.'
  python3 - "$PROJECT_ROOT/applications/golden-path-api/requirements" <<'PY'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
for stem in ("runtime", "test"):
    inputs = {
        line.strip().lower()
        for line in (root / f"{stem}.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(("#", "-r "))
    }
    locked = {
        match.group(0).lower()
        for match in re.finditer(
            r"(?m)^[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+",
            (root / f"{stem}.txt").read_text(encoding="utf-8"),
        )
    }
    missing = sorted(inputs - locked)
    if missing:
        raise SystemExit(f"{stem}.txt does not contain direct inputs: {missing}")
PY
  printf '%s\n' 'PASS  runtime and test dependency locks contain hashes and installation enforces them.'
}

update_locks() {
  require_command docker
  requirements=$PROJECT_ROOT/applications/golden-path-api/requirements
  docker build --tag "$LOCK_COMPILER_IMAGE" "$PROJECT_ROOT/tools/dependency-lock"
  for stem in runtime test; do
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
      -v "$requirements:/requirements" "$LOCK_COMPILER_IMAGE" \
      --upgrade --generate-hashes --resolver=backtracking --strip-extras \
      --output-file="$stem.txt" "$stem.in"
  done
  verify_locks
}

usage() {
  printf 'usage: %s {build-artifact|load-artifact|inspect|policy|policy-test|secret-scan|sbom|scan|locks|locks-update}\n' "$0" >&2
  exit 2
}

case ${1:-} in
  build-artifact) build_artifact ;;
  load-artifact) load_artifact ;;
  inspect) inspect_image ;;
  policy) validate_policy ;;
  policy-test) policy_tests ;;
  secret-scan) secret_scan ;;
  sbom) generate_sbom ;;
  scan) scan_image ;;
  locks) verify_locks ;;
  locks-update) update_locks ;;
  *) usage ;;
esac
