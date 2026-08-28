#!/usr/bin/env python3
"""Static and pure regression tests for the guarded Argo installation."""

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    common = (ROOT / "scripts/lib/gitops-common.sh").read_text(encoding="utf-8")
    installer = (ROOT / "scripts/gitops.sh").read_text(encoding="utf-8")
    match = re.search(r"^ARGOCD_INSTALL_TIMEOUT_SECONDS=([0-9]+)$", common, re.MULTILINE)
    assert match
    timeout = int(match.group(1))
    assert 600 <= timeout <= 1200
    assert timeout == 900
    assert installer.count("helm upgrade --install") == 1
    helm = installer[installer.index("if helm upgrade --install"):installer.index("resolve_argocd_api_endpoint \"$temporary\" snapshot-c")]
    assert "--atomic" in helm and "--wait" in helm
    assert '--timeout "${ARGOCD_INSTALL_TIMEOUT_SECONDS}s"' in helm
    assert "capture-gitops-install-failure.py" in helm
    assert "return \"$gitops_helm_status\"" in helm
    assert not re.search(r"(?:while|until).*helm upgrade", installer)
    assert "retry" not in helm.lower()
    hardening = installer[installer.index("harden_default_project()") : installer.index("harden_default_project_guarded()")]
    assert "--server-side" in hardening and "--field-manager=platform-engineering-lab" in hardening
    assert "validate-default-appproject.py" in hardening and "ARGOCD_DEFAULT_PROJECT_SHA256" in hardening
    assert installer.index("harden_default_project\n") < installer.index('resolve_argocd_api_endpoint "$temporary" snapshot-c')
    assert "confirm_exact argocd-default-project-deny-all" in installer
    subprocess.run(["python3", str(ROOT / "scripts/capture-gitops-install-failure.py"), "--self-test"], check=True)
    subprocess.run(["python3", str(ROOT / "scripts/validate-default-appproject.py"), "--self-test"], check=True)
    subprocess.run(["python3", str(ROOT / "scripts/check-optional-argo-application.py"), "--self-test"], check=True)
    print("PASS  Argo installation uses one atomic, waited, non-retried Helm execution with a fixed 15-minute timeout and failure diagnostics.")


if __name__ == "__main__":
    main()
