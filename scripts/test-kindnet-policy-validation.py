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
            prefix = enforcement / f"kindnet-dns-{index}-fixture"
            for suffix in ("created.json", "log", "pod.json", "describe", "events.json", "cleanup.json"):
                pathlib.Path(f"{prefix}-{suffix}").write_text("{}\n")
        run("python3", str(EVIDENCE_VALIDATOR), "evidence", "--root", str(enforcement))
        manifest = json.loads((enforcement / "evidence-manifest.json").read_text())
        assert manifest["schemaVersion"] == 1 and manifest["files"]
        (enforcement / "kindnet-dns-0-fixture-log").unlink()
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
    print("PASS  kindnet validation fixes the exact artifact-base defect and preserves strict path containment.")
    print("PASS  validation-only mode accepts fresh Pod identities, tests both workers, and cannot invoke recovery.")


if __name__ == "__main__":
    main()
