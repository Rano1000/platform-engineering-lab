#!/usr/bin/env python3
"""Offline safety tests for kindnet validation evidence and artifact containment."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH_VALIDATOR = ROOT / "scripts/validate-diagnostic-path.py"
EVIDENCE_VALIDATOR = ROOT / "scripts/validate-kindnet-enforcement.py"
DIAGNOSTIC_COMMON = ROOT / "scripts/lib/diagnostic-common.sh"


def run(*arguments: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, text=True, capture_output=True, check=False)
    assert (result.returncode == 0) is ok, (arguments, result.stdout, result.stderr)
    return result


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

        for index in (0, 1):
            worker = enforcement / f"worker-{index}"; worker.mkdir(exist_ok=True)
            (worker / "evidence-manifest.json").write_text('{"schemaVersion":1,"files":{}}\n')
        for name in ("daemonset.json", "pods.json", "kindnet.log", "identity.json"):
            (enforcement / name).write_text("{}\n")
        for index in (0, 1):
            name = f"kindnet-dns-{index}-fixture"
            files = {kind: f"{name}.{suffix}" for kind, suffix in {
                "created":"created.json", "log":"pod.log", "pod":"pod.json", "describe":"describe.txt",
                "events":"events.json", "cleanup":"cleanup.json"}.items()}
            for filename in files.values(): (enforcement / filename).write_text("{}\n")
            (enforcement / f"{name}.artifacts.json").write_text(json.dumps({
                "schemaVersion":1,"name":name,"namespace":"gitops","node":f"worker-{index}",
                "uid":f"uid-{index}","files":files}, sort_keys=True)+"\n")
        run("python3", str(EVIDENCE_VALIDATOR), "evidence", "--root", str(enforcement))
        manifest = json.loads((enforcement / "evidence-manifest.json").read_text())
        assert manifest["schemaVersion"] == 1 and manifest["files"]
        (enforcement / "kindnet-dns-0-fixture.describe.txt").unlink()
        run("python3", str(EVIDENCE_VALIDATOR), "evidence", "--root", str(enforcement), ok=False)

    harness = (ROOT / "scripts/test-kindnet-policy.sh").read_text(encoding="utf-8")
    recovery = (ROOT / "scripts/kindnet-policy-recover.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "GITOPS_NETWORK_ARTIFACT_BASE=\"$knp_root\"" in harness
    assert "KINDNET_POLICY_REQUIRE_CONFIRMATION" in harness
    assert "validate-kindnet-recovery.py\" preflight" in harness
    assert harness.count("GITOPS_NETWORK_WORKER_INDEX=$knp_index") == 1
    assert "for knp_index in 0 1" in harness
    assert "kindnet-dns-probe.py\" pod-overrides" in harness
    assert "case $knp_dns_phase in Succeeded|Failed" in harness
    assert harness.count("diagnostic_artifact_name") >= 8
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
