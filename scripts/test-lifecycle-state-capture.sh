#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd)
temporary=$(mktemp -d "${TMPDIR:-/tmp}/gitops-lifecycle.XXXXXX")
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
fixture=$temporary/child.json
first=$temporary/first
second=$temporary/second

printf '%s\n' '{"apiVersion":"argoproj.io/v1alpha1","kind":"Application","metadata":{"name":"golden-path-api","namespace":"gitops"},"spec":{"project":"platform-apps"}}' >"$fixture"
PLATFORM_LAB_SELF_TEST=1 GITOPS_LIFECYCLE_FIXTURE=$fixture \
  "$SCRIPT_DIR/gitops.sh" self-test-lifecycle "$first"
PLATFORM_LAB_SELF_TEST=1 GITOPS_LIFECYCLE_FIXTURE=$fixture \
  "$SCRIPT_DIR/gitops.sh" self-test-lifecycle "$second"
cmp "$first/live-child-state.json" "$second/live-child-state.json"
python3 - "$first/live-child-state.json" <<'PY'
import hashlib, json, pathlib, sys
record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert set(record) == {"schemaVersion", "context", "namespace", "name", "state", "object", "objectSha256"}
assert record["schemaVersion"] == 1
assert (record["context"], record["namespace"], record["name"], record["state"]) == (
    "kind-platform-engineering-lab", "gitops", "golden-path-api", "present"
)
canonical = json.dumps(record["object"], sort_keys=True, separators=(",", ":"))
assert hashlib.sha256(canonical.encode()).hexdigest() == record["objectSha256"]
PY
printf '%s\n' 'PASS  lifecycle-state shell entry point emits deterministic, checksummed schema-valid evidence.'
