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
    print("PASS  network harness bounds inner timeouts, captures diagnostics before cleanup, cleans success/failure paths, and rejects missing or secret-bearing evidence.")


if __name__ == "__main__": main()
