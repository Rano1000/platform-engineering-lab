#!/usr/bin/env python3
"""Pure structural regression tests for the guarded network harness."""

import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    harness = (ROOT / "scripts/test-gitops-network.sh").read_text()
    assert "INNER_TIMEOUT_SECONDS=2" in harness and "OUTER_TIMEOUT_SECONDS=20" in harness
    assert harness.index("capture_diagnostics") < harness.index("cleanup_resources")
    assert "validate_diagnostics" in harness and "diagnostics_complete=1" in harness
    assert "if validate_diagnostics" in harness and "[ -s \"$diagnostics/" in harness
    assert ".artifacts/gitops-network" in harness
    assert all(name in harness for name in ("pod.json", "pod.log", "describe.txt", "events.json", "networkpolicies.yaml", "endpoint-identity.json", "node.json"))
    assert harness.count("run_case ") >= 12
    assert "automountServiceAccountToken" in (ROOT / "scripts/network-probe.py").read_text()
    for function in ("sanitize_file", "capture_pod", "capture_diagnostics", "validate_diagnostics", "cleanup_resources", "validate_result"):
        assert f"{function}() (" in harness
    assert harness.index('capture_diagnostics\n  [ "$gnt_case_phase"') < harness.index('kubectl_lab delete pod "$gnt_case_pod"')
    finish = harness[harness.index("finish() {"):harness.index("trap finish EXIT")]
    assert finish.index("validate_diagnostics") < finish.index("cleanup_resources")
    assert 'if [ "$diagnostics_complete" = 1 ]' in finish
    shell_test = r'''
set -eu
caller_destination='run dir/pods/pod one'
sanitize_file() (
  gnt_sanitize_source=$1
  gnt_sanitize_output=$2
  test -n "$gnt_sanitize_source" && test -n "$gnt_sanitize_output"
)
sanitize_file input 'run dir/pods/pod one/pod.json'
test "$caller_destination" = 'run dir/pods/pod one'
'''
    subprocess.run(["/bin/sh", "-c", shell_test], check=True)
    with tempfile.TemporaryDirectory() as state_directory:
        lifecycle_test = r'''
set -eu
state=$1
cleanup_resources() ( : >"$state/cleaned"; )
complete=1
if [ "$complete" = 1 ]; then cleanup_resources; fi
complete=0
if [ "$complete" = 1 ]; then cleanup_resources; else : >"$state/preserved"; fi
'''
        subprocess.run(["/bin/sh", "-c", lifecycle_test, "sh", state_directory], check=True)
        assert (pathlib.Path(state_directory) / "cleaned").is_file()
        assert (pathlib.Path(state_directory) / "preserved").is_file()
    with tempfile.TemporaryDirectory() as directory:
        safe = pathlib.Path(directory) / "safe.json"; safe.write_text('{"result":"tcp_timeout"}')
        subprocess.run(["python3", str(ROOT / "scripts/redact-network-diagnostics.py"), str(safe)], check=True, capture_output=True)
        unsafe = pathlib.Path(directory) / "unsafe.json"; unsafe.write_text('{"env":[{"name":"TOKEN","value":"secret"}]}')
        result = subprocess.run(["python3", str(ROOT / "scripts/redact-network-diagnostics.py"), str(unsafe)], capture_output=True)
        assert result.returncode != 0
        sanitized = pathlib.Path(directory) / "sanitized.json"
        subprocess.run(["python3", str(ROOT / "scripts/redact-network-diagnostics.py"), "--sanitize", str(unsafe), str(sanitized)], check=True)
        assert "secret" not in sanitized.read_text() and "[REDACTED]" in sanitized.read_text()
        missing = pathlib.Path(directory) / "missing"
        assert not missing.exists()
        base = pathlib.Path(directory) / "base with spaces"
        root = base / "run_+[safe]"
        for pod in ("pod-one", "pod-two"):
            pod_dir = root / "pods" / pod
            subprocess.run(["python3", str(ROOT / "scripts/validate-diagnostic-path.py"), "ensure-dir", "--base", str(base), "--root", str(root), "--path", str(pod_dir)], check=True)
            for name in ("pod.log", "pod.json", "describe.txt", "events.json"): (pod_dir / name).write_text("evidence")
        assert (root / "pods/pod-one/pod.json").is_file() and not (root / "pods/pod-one/pod.json").is_dir()
        required = ("pod.log", "pod.json", "describe.txt", "events.json")
        for missing_name in ("pod.log", "describe.txt", "events.json"):
            target = root / "pods/pod-two" / missing_name
            target.unlink()
            assert not all((root / "pods/pod-two" / name).is_file() for name in required)
            target.write_text("evidence")
    print("PASS  POSIX-shell helper isolation preserves caller state; sequential capture, path safety, completeness, capture-before-cleanup, and failure preservation contracts pass.")


if __name__ == "__main__": main()
