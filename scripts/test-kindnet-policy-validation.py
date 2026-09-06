#!/usr/bin/env python3
"""Offline safety tests for kindnet validation evidence and artifact containment."""

from __future__ import annotations

import json
import importlib.util
import os
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH_VALIDATOR = ROOT / "scripts/validate-diagnostic-path.py"
EVIDENCE_VALIDATOR = ROOT / "scripts/validate-kindnet-enforcement.py"
DIAGNOSTIC_COMMON = ROOT / "scripts/lib/diagnostic-common.sh"
PROJECTOR = ROOT / "scripts/project-kindnet-evidence.py"
RECOVERY_VALIDATOR = ROOT / "scripts/validate-kindnet-recovery.py"
SCANNER = ROOT / "scripts/redact-network-diagnostics.py"


def run(*arguments: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, text=True, capture_output=True, check=False)
    assert (result.returncode == 0) is ok, (arguments, result.stdout, result.stderr)
    return result


def write_complete_tree(root: pathlib.Path) -> None:
    (root / "daemonset.json").write_text(json.dumps({"schemaVersion": 1, "projectionType": "kindnet-daemonset", "daemonSet": {}}) + "\n")
    projected_pod = {"metadata": {"name": "kindnet", "uid": "uid"}, "nodeName": "worker", "container": {"image": "pinned"}}
    (root / "pods.json").write_text(json.dumps({"schemaVersion": 1, "projectionType": "kindnet-pod-list", "items": [projected_pod] * 3}) + "\n")
    (root / "kindnet.log").write_text("watchers healthy\n")
    (root / "identity.json").write_text('{"schemaVersion":1}\n')
    for index in (0, 1):
        worker = root / f"worker-{index}"; pods = worker / "pods"; cleanup = worker / "cleanup"
        pods.mkdir(parents=True); cleanup.mkdir()
        for filename in ("endpoint-identity.json", "endpointslices.json", "node.json"):
            (worker / filename).write_text("{}\n")
        (worker / "networkpolicies.yaml").write_text("items: []\n")
        names = [f"assertion-{number}" for number in range(12)] + ["listener"]
        for name in names:
            directory = pods / name; directory.mkdir()
            for filename in ("pod.json", "events.json"):
                (directory / filename).write_text("{}\n")
            (directory / "pod.log").write_text('{"exit_code":0}\n')
            (directory / "describe.txt").write_text("safe description\n")
        for number in range(14):
            (cleanup / f"resource-{number}.json").write_text('{"success":true,"cleanupResult":"deleted"}\n')
    for index in (0, 1):
        name = f"kindnet-dns-{index}-fixture"
        files = {kind: f"{name}.{suffix}" for kind, suffix in {
            "created":"created.json", "log":"pod.log", "pod":"pod.json", "describe":"describe.txt",
            "events":"events.json", "cleanup":"cleanup.json"}.items()}
        for kind, filename in files.items():
            content = '{"success":true,"cleanupResult":"deleted"}\n' if kind == "cleanup" else "{}\n"
            (root / filename).write_text(content)
        (root / f"{name}.artifacts.json").write_text(json.dumps({
            "schemaVersion":1,"name":name,"namespace":"gitops","node":f"worker-{index}",
            "uid":f"uid-{index}","files":files}, sort_keys=True)+"\n")


def raw_fixture():
    path = ROOT / "scripts/test-kindnet-evidence-projection.py"
    specification = importlib.util.spec_from_file_location("kindnet_projection_fixtures", path)
    module = importlib.util.module_from_spec(specification); specification.loader.exec_module(module)
    daemonset = module.fixture(); daemonset["metadata"]["uid"] = "daemonset-uid"
    nodes = ("platform-engineering-lab-control-plane", "platform-engineering-lab-worker", "platform-engineering-lab-worker2")
    pods = []
    for index, node in enumerate(nodes):
        pod = module.pod_fixture(f"kindnet-{index}"); pod["spec"]["nodeName"] = node
        pod["metadata"]["ownerReferences"][0]["uid"] = "daemonset-uid"; pods.append(pod)
    return daemonset, {"apiVersion": "v1", "kind": "PodList", "items": pods}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="kindnet validation + safe_") as directory:
        artifacts = pathlib.Path(directory) / ".artifacts"
        gitops_base = artifacts / "gitops-network"
        enforcement = artifacts / "kindnet-policy-enforcement" / "run one"
        rejected = enforcement / "worker-0"
        # Exact former defect: a kindnet path cannot be validated against the unrelated GitOps base.
        result = run(
            "python3", str(PATH_VALIDATOR), "ensure-dir", "--base", str(gitops_base),
            "--root", str(rejected), "--path", str(rejected / "pods"), ok=False,
        )
        assert "escapes its approved run directory" in result.stderr
        # Correct contract: the explicit kindnet run is validated beneath the global artifact boundary.
        run(
            "python3", str(PATH_VALIDATOR), "ensure-dir", "--base", str(artifacts),
            "--root", str(enforcement), "--path", str(rejected / "pods with spaces + safe_[1]"),
        )
        collision = pathlib.Path(str(enforcement) + "-collision")
        run(
            "python3", str(PATH_VALIDATOR), "ensure-dir", "--base", str(artifacts),
            "--root", str(enforcement), "--path", str(collision), ok=False,
        )
        traversal = enforcement / ".." / "outside"
        run(
            "python3", str(PATH_VALIDATOR), "ensure-dir", "--base", str(artifacts),
            "--root", str(enforcement), "--path", str(traversal), ok=False,
        )
        link = enforcement / "link"; link.symlink_to(directory)
        run(
            "python3", str(PATH_VALIDATOR), "ensure-dir", "--base", str(artifacts),
            "--root", str(enforcement), "--path", str(link / "child"), ok=False,
        )
        fifo = enforcement / "fifo"; os.mkfifo(fifo)
        run(
            "python3", str(PATH_VALIDATOR), "ensure-output", "--base", str(artifacts),
            "--root", str(enforcement), "--path", str(fifo), ok=False,
        )
        fifo.unlink(); link.unlink()

        write_complete_tree(enforcement)
        raw = pathlib.Path(directory) / "private raw"; raw.mkdir(mode=0o700)
        daemonset, pods = raw_fixture()
        (raw / "daemonset.json").write_text(json.dumps(daemonset)); (raw / "pods.json").write_text(json.dumps(pods))
        (raw / "kindnet.log").write_text("watchers healthy\n")
        entry = pathlib.Path(directory) / "pipeline.sh"
        entry.write_text(
            "#!/bin/sh\nset -eu\numask 077\n"
            "raw=$1 evidence=$2 scripts=$3\n"
            "python3 \"$scripts/validate-kindnet-recovery.py\" preflight --daemonset \"$raw/daemonset.json\" --pods \"$raw/pods.json\" "
            "--image docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88 --output \"$raw/identity.json\"\n"
            "python3 \"$scripts/validate-kindnet-enforcement.py\" preflight --daemonset \"$raw/daemonset.json\" --pods \"$raw/pods.json\" --logs \"$raw/kindnet.log\"\n"
            "python3 \"$scripts/validate-kindnet-recovery.py\" confirmation --identity \"$raw/identity.json\" --context kind-platform-engineering-lab >/dev/null\n"
            "python3 \"$scripts/project-kindnet-evidence.py\" --source \"$raw/daemonset.json\" --output \"$evidence/daemonset.json\"\n"
            "python3 \"$scripts/project-kindnet-evidence.py\" --source \"$raw/pods.json\" --output \"$evidence/pods.json\"\n"
            "python3 \"$scripts/validate-kindnet-enforcement.py\" inventory --root \"$evidence\"\n"
            "find \"$evidence\" -type f ! -name evidence-manifest.json -print0 | xargs -0 python3 \"$scripts/redact-network-diagnostics.py\"\n"
            "python3 \"$scripts/validate-kindnet-enforcement.py\" evidence --root \"$evidence\"\n",
            encoding="utf-8",
        )
        run("/bin/sh", str(entry), str(raw), str(enforcement), str(ROOT / "scripts"))
        run("python3", str(EVIDENCE_VALIDATOR), "inventory", "--root", str(enforcement))
        (enforcement / "evidence-manifest.json").unlink()
        run("python3", str(EVIDENCE_VALIDATOR), "evidence", "--root", str(enforcement))
        manifest = json.loads((enforcement / "evidence-manifest.json").read_text())
        assert manifest["schemaVersion"] == 1 and len(manifest["files"]) == 158
        (enforcement / "evidence-manifest.json").unlink()
        hidden = enforcement / "worker-0" / "pods" / "assertion-0" / "pod.json"
        original = hidden.read_text()
        hidden.write_text(json.dumps({"apiVersion":"v1","kind":"Pod","metadata":{"labels":{"app":"kindnet"}}})+"\n")
        run("python3", str(EVIDENCE_VALIDATOR), "inventory", "--root", str(enforcement), ok=False)
        assert not (enforcement / "evidence-manifest.json").exists()
        hidden.write_text(original)
        raw_pods = enforcement / "pods.json"; projected_pods = raw_pods.read_text()
        raw_pods.write_text(json.dumps({"apiVersion":"v1","kind":"PodList","items":[]})+"\n")
        rejected_raw = run("python3", str(EVIDENCE_VALIDATOR), "inventory", "--root", str(enforcement), ok=False)
        assert "rejects raw Kubernetes objects" in rejected_raw.stderr
        raw_pods.write_text(projected_pods)
        (enforcement / "kindnet-dns-0-fixture.describe.txt").unlink()
        run("python3", str(EVIDENCE_VALIDATOR), "evidence", "--root", str(enforcement), ok=False)
        assert not (enforcement / "evidence-manifest.json").exists()

        # Unknown files and hidden unprojected kindnet workloads fail before atomic manifest creation.
        (enforcement / "kindnet-dns-0-fixture.describe.txt").write_text("safe description\n")
        (enforcement / "unexpected.json").write_text(json.dumps({"kind":"Pod","metadata":{"labels":{"app":"kindnet"}}})+"\n")
        run("python3", str(EVIDENCE_VALIDATOR), "evidence", "--root", str(enforcement), ok=False)
        assert not (enforcement / "evidence-manifest.json").exists()
        (enforcement / "unexpected.json").unlink()
        empty = enforcement / "worker-0" / "pods" / "assertion-0" / "pod.log"
        empty.write_text("")
        run("python3", str(EVIDENCE_VALIDATOR), "evidence", "--root", str(enforcement), ok=False)
        assert not (enforcement / "evidence-manifest.json").exists()

    harness = (ROOT / "scripts/test-kindnet-policy.sh").read_text(encoding="utf-8")
    recovery = (ROOT / "scripts/kindnet-policy-recover.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "GITOPS_NETWORK_ARTIFACT_BASE=\"$knp_root\"" in harness
    assert "umask 077" in harness and "knp_raw_private=$(mktemp -d)" in harness
    assert '--pods "$knp_raw_private/pods.json"' in harness
    assert harness.index('validate-kindnet-enforcement.py" preflight') < harness.index('project-kindnet-evidence.py')
    assert 'trap knp_cleanup_raw EXIT' in harness and "trap 'exit 130' INT" in harness
    assert "KINDNET_POLICY_REQUIRE_CONFIRMATION" in harness
    assert "validate-kindnet-recovery.py\" preflight" in harness
    assert harness.count("GITOPS_NETWORK_WORKER_INDEX=$knp_index") == 1
    assert "for knp_index in 0 1" in harness
    assert "kindnet-dns-probe.py\" pod-overrides" in harness
    assert "case $knp_dns_phase in Succeeded|Failed" in harness
    assert harness.count("diagnostic_artifact_name") >= 8
    assert harness.count("project-kindnet-evidence.py") >= 2
    assert "retry" not in harness.lower()
    assert "rollout restart" not in harness and "delete daemonset" not in harness
    assert "kindnet-policy-validate:" in makefile
    validate_recipe = makefile.split("kindnet-policy-validate:", 1)[1].split("\n\n", 1)[0]
    assert "KINDNET_POLICY_REQUIRE_CONFIRMATION=1" in validate_recipe
    assert "kindnet-policy-recover" not in validate_recipe
    assert "cleanup-kubernetes-resource.py" not in recovery[recovery.index('"$SCRIPT_DIR/test-kindnet-policy.sh"') :]
    shell = """
set -eu
caller_root='approved root with spaces'
helper() (
  helper_root=$1
  test "$helper_root" = 'nested value'
)
helper 'nested value'
test "$caller_root" = 'approved root with spaces'
"""
    run("/bin/sh", "-c", shell)
    with tempfile.TemporaryDirectory(prefix="raw trap ") as directory:
        marker = pathlib.Path(directory) / "raw-path"
        trap_script = pathlib.Path(directory) / "trap.sh"
        trap_script.write_text(
            "#!/bin/sh\nset -eu\numask 077\nraw=$(mktemp -d)\nprintf '%s' \"$raw\" >\"$1\"\n"
            "cleanup() { status=$?; trap - EXIT HUP INT TERM; rm -rf \"$raw\"; exit \"$status\"; }\n"
            "trap cleanup EXIT\ntrap 'exit 129' HUP\ntrap 'exit 130' INT\ntrap 'exit 143' TERM\nexit \"$2\"\n",
            encoding="utf-8",
        )
        for status in (0, 7):
            result = subprocess.run(["/bin/sh", str(trap_script), str(marker), str(status)], check=False)
            assert result.returncode == status
            assert not pathlib.Path(marker.read_text()).exists()
    canonical = subprocess.run([
        "/bin/sh", "-c",
        f'. {DIAGNOSTIC_COMMON!s}; '
        'for kind in created log pod describe events cleanup; do diagnostic_artifact_name "pod safe_+1" "$kind"; done',
    ], text=True, capture_output=True)
    assert canonical.returncode != 0  # Spaces are safe in directories, not Kubernetes-derived artifact prefixes.
    entry = subprocess.run([
        "/bin/sh", "-c",
        f'. {DIAGNOSTIC_COMMON!s}; '
        'for kind in created log pod describe events cleanup; do diagnostic_artifact_name kindnet-dns-0-run_+1 "$kind"; done',
    ], text=True, capture_output=True, check=True)
    assert entry.stdout.splitlines() == [
        "kindnet-dns-0-run_+1.created.json", "kindnet-dns-0-run_+1.pod.log",
        "kindnet-dns-0-run_+1.pod.json", "kindnet-dns-0-run_+1.describe.txt",
        "kindnet-dns-0-run_+1.events.json", "kindnet-dns-0-run_+1.cleanup.json",
    ]
    assert "kindnet-dns-0-1788566836-85685.describe" not in harness
    assert "kindnet-dns-0-1788566836-85685-describe" not in harness
    with tempfile.TemporaryDirectory(prefix="dns entry point ") as directory:
        root = pathlib.Path(directory); raw = root / "raw"; evidence = root / "evidence"
        raw.mkdir(); evidence.mkdir(); name = "kindnet-dns-0-posix_+1"
        for suffix in ("created.json", "pod.log", "pod.json", "describe.txt", "events.json", "cleanup.json"):
            (raw / f"{name}.{suffix}").write_text("{}\n")
        entry_script = root / "entry.sh"
        entry_script.write_text(
            "#!/bin/sh\nset -eu\n"
            f'. {DIAGNOSTIC_COMMON!s}\n'
            "raw=$1 evidence=$2 name=$3 scripts=$4\n"
            "for kind in created log pod describe events cleanup; do\n"
            "  artifact=$(diagnostic_artifact_name \"$name\" \"$kind\")\n"
            "  python3 \"$scripts/redact-network-diagnostics.py\" --sanitize \"$raw/$artifact\" \"$evidence/$artifact\"\n"
            "done\n"
            "python3 \"$scripts/validate-kindnet-enforcement.py\" dns-manifest --root \"$evidence\" "
            "--name \"$name\" --node worker-1 --uid uid-1\n",
            encoding="utf-8",
        )
        run("/bin/sh", str(entry_script), str(raw), str(evidence), name, str(ROOT / "scripts"))
        record = json.loads((evidence / f"{name}.artifacts.json").read_text())
        assert set(record["files"]) == {"created", "log", "pod", "describe", "events", "cleanup"}
    print("PASS  kindnet validation fixes the exact artifact-base defect and preserves strict path containment.")
    print("PASS  validation-only mode accepts fresh Pod identities, tests both workers, and cannot invoke recovery.")


if __name__ == "__main__":
    main()
