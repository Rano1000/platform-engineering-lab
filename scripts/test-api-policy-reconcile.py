#!/usr/bin/env python3
"""Static and pure tests for the policy-only reconciliation transaction."""

import pathlib
import re
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    script = (ROOT / "scripts/gitops.sh").read_text(encoding="utf-8")
    start = script.index("reconcile_api_policies() (")
    end = script.index("\nbootstrap_gitops()", start)
    transaction = script[start:end]
    assert "gitops-api-policy-reconcile:" in makefile
    assert "reconcile-api-policies" in makefile
    assert "require_clean_synchronized_repository" in transaction
    assert all(f"snapshot-{name}" in transaction for name in ("a", "b", "c"))
    assert "snapshot-confirmed" in transaction
    assert transaction.count("compare_argocd_api_snapshots") == 3
    assert "verify-pre" in transaction and "verify-after" in transaction
    assert "--show-managed-fields=true" in transaction
    assert "gitops_policy_state\" = current" in transaction
    assert "argocd-api-endpoint-policies/$gitops_policy_old/$gitops_policy_new" in transaction
    assert not re.search(r"(^|[;&|]\s*)helm\s", transaction, re.MULTILINE)
    assert "run_argocd_core" not in transaction and "gitops-root-sync" not in transaction and "gitops-app-sync" not in transaction
    assert not re.search(r"kubectl_lab\s+(?:apply|delete|replace|create)", transaction)
    assert transaction.count('python3 "$gitops_policy_validator" apply') == 1
    assert "evidence-manifest.json" in transaction and "redact-network-diagnostics.py" in transaction
    subprocess.run(["python3", str(ROOT / "scripts/reconcile-argocd-api-policies.py"), "self-test"], check=True)
    subprocess.run(["python3", str(ROOT / "scripts/validate-argocd-workload.py"), "--self-test"], check=True)
    print("PASS  policy-only reconciliation is checksummed, race-guarded, idempotent, and cannot invoke Helm or Argo synchronization.")


if __name__ == "__main__":
    main()
