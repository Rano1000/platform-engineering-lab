#!/usr/bin/env python3
"""Offline regression tests for the application network-test transaction."""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts/test-app-network.sh"
PROBE = ROOT / "scripts/app-network-probe.py"


def require_order(content: str, earlier: str, later: str) -> None:
    assert content.index(earlier) < content.index(later), (earlier, later)


def main() -> None:
    content = HARNESS.read_text(encoding="utf-8")
    app = (ROOT / "scripts/app.sh").read_text(encoding="utf-8")
    assert 'exec "$SCRIPT_DIR/test-app-network.sh"' in app
    assert "--ignore-not-found" not in content
    assert "kubectl_lab delete" not in content
    assert "--selector" not in content and "-l platform.engineering-lab" not in content
    assert 'ANT_MAX_SIMULTANEOUS_RESOURCES=5' in content
    assert content.count("kubectl_lab run") == 3  # Listener, reachability preflight, and reusable assertion Pod.
    require_order(content, 'ant_run_case "$ant_allowed"', 'ant_run_case "$ant_denied"')
    require_order(content, 'ant_cleanup_resource pod "$ant_rc_name"', 'ant_run_case "$ant_denied"')
    run_case = content[content.index("ant_run_case() {"):content.index('ant_run_case "$ant_allowed"')]
    require_order(run_case, "ant_capture_pod \"$ant_rc_name\"", "ant_cleanup_resource pod")
    require_order(run_case, "ant_validate_pod_diagnostics", "ant_cleanup_resource pod")
    normal_flow = content[content.index('ant_run_case "$ant_allowed"'):]
    require_order(normal_flow, "ant_capture_context", "ant_cleanup_resource networkpolicy")
    assert 'cleanup-kubernetes-resource.py" cleanup' in content
    assert '--kind "$ant_cr_kind"' in content and '--uid "$ant_cr_uid"' in content
    assert "ant_validate_cleanup_evidence" in content
    for allowed in ("deleted", "already_absent", "already_absent_after_race"):
        assert allowed in content
    assert 'ant_preserve_resources=1' in content
    assert 'if [ "$ant_preserve_resources" -eq 0 ]' in content
    assert 'find "$ant_diagnostics" -type l' in content
    assert 'find "$ant_diagnostics" ! -type d ! -type f' in content
    assert "redact-network-diagnostics.py" in content and "validate-diagnostic-path.py" in content
    assert "ant_write_evidence_manifest" in content and 'os.replace(temporary, root / "evidence-manifest.json")' in content
    for required in (
        "pod.json", "pod.log", "describe.txt", "events.json", "pre-test.json", "phase-poll.log",
        "temporary-policy.yaml", "temporary-ingress-policy.yaml", "listener-policy.yaml", "application-policy.yaml", "runtime-identities.json",
        "approved-internal-metrics", "unapproved-internal-metrics-deny",
        "approved-outside-flow-deny", "approved-internet-deny", "approved-kubernetes-api-deny",
        "unapproved-internet-deny", "unapproved-kubernetes-api-deny", "public-$ant_public_case-blocked",
        "/metrics", "/health/live", "/health/ready",
    ):
        assert required in content, required
    assert 'ANT_INNER_TIMEOUT_SECONDS=3' in content
    assert 'ANT_OUTER_TIMEOUT_SECONDS=30' in content
    assert content.index("ANT_INNER_TIMEOUT_SECONDS=3") < content.index("ANT_OUTER_TIMEOUT_SECONDS=30")
    assert 'case $ant_rc_phase in Succeeded|Failed|api_error)' in content
    assert 'ant_finish_status=$?' in content and 'ant_assertion_status' in content and 'ant_cleanup_status' in content
    assert "app-network-policy-test" in content
    assert "automountServiceAccountToken" in PROBE.read_text(encoding="utf-8")
    assert '"$SCRIPT_DIR/test-kindnet-policy.sh"' in content
    assert 'listener-overrides' in content and 'port 9090' in content
    assert 'approved-outside-flow-deny' in content and '"port":9090' in content
    assert 'namespace: $APP_NAMESPACE' in content and 'name: $ant_ingress_policy' in content
    assert 'platform.engineering-lab/run-id: $ant_suffix' in content
    assert 'kubernetes.io/metadata.name: $ANT_NAMESPACE' in content
    assert 'platform.engineering-lab/purpose: metrics-test' in content
    assert 'port":8081' not in content

    permanent = (ROOT / "charts/golden-path-api/templates/networkpolicy.yaml").read_text(encoding="utf-8")
    assert "observability" not in permanent and "metricsTest" not in permanent
    assert permanent.count("namespaceSelector") == 1 and "platform-system" in permanent
    project = (ROOT / "environments/local/gitops/workload-project.yaml").read_text(encoding="utf-8")
    assert 'namespace: platform-apps' in project and 'namespace: "*"' not in project

    kindnet_test = (ROOT / "scripts/test-kindnet-policy.sh").read_text(encoding="utf-8")
    assert 'GITOPS_NETWORK_WORKER_INDEX=$knp_index' in kindnet_test
    assert "for knp_index in 0 1" in kindnet_test
    assert kindnet_test.index("validate-kindnet-enforcement.py\" preflight") < kindnet_test.index("test-gitops-network.sh")
    recovery = (ROOT / "scripts/kindnet-policy-recover.sh").read_text(encoding="utf-8")
    assert 'confirm_exact "$kpr_confirmation"' in recovery
    assert recovery.count('cleanup-kubernetes-resource.py" cleanup') == 1
    assert 'test-kindnet-policy.sh' in recovery and "retry" not in recovery.lower()
    assert recovery.index('cleanup-kubernetes-resource.py" cleanup') < recovery.index('kubectl_lab wait')

    subprocess.run(["python3", str(PROBE), "self-test"], check=True)
    subprocess.run(["python3", str(ROOT / "scripts/cleanup-kubernetes-resource.py"), "self-test"], check=True)
    subprocess.run(["python3", str(ROOT / "scripts/validate-diagnostic-path.py"), "self-test"], check=True)

    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory)
        cases = path / "cases.json"
        cases.write_text(json.dumps([{
            "name": "approved-internal-metrics", "identity": "approved-observability",
            "host": "10.96.0.10", "port": 80, "expected": "allow", "mode": "http",
            "path": "/metrics", "expected_status": 200, "body_contains": "golden_path_http_requests_total",
        }]), encoding="utf-8")
        generated = subprocess.run([
            "python3", str(PROBE), "pod-overrides", "--node", "worker one",
            "--image", "ghcr.io/rano1000/golden-path-api@sha256:" + "a" * 64,
            "--cases", str(cases), "--timeout", "3",
        ], check=True, text=True, stdout=subprocess.PIPE).stdout
        pod = json.loads(generated)
        assert pod["spec"]["nodeName"] == "worker one"
        assert pod["spec"]["automountServiceAccountToken"] is False
        assert pod["spec"]["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        security = pod["spec"]["containers"][0]["securityContext"]
        assert security["readOnlyRootFilesystem"] and security["capabilities"]["drop"] == ["ALL"]

    # Cleanup state coverage includes UID mismatch/name reuse, verified races, RBAC, API, and timeout failures.
    cleanup = (ROOT / "scripts/cleanup-kubernetes-resource.py").read_text(encoding="utf-8")
    for state in (
        "already_absent_after_race", "name_reused", "authorization_error",
        "api_connectivity_error", "deletion_timeout", "original_uid_still_present",
    ):
        assert state in cleanup
    print("PASS  application network harness preserves diagnostics, bounded quotas, assertion status, and UID-aware observable cleanup.")


if __name__ == "__main__":
    main()
