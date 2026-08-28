#!/usr/bin/env python3
"""Delete one exact Kubernetes resource and retain a sanitized cleanup decision."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
REDACTOR_SPEC = importlib.util.spec_from_file_location(
    "network_diagnostic_redactor", ROOT / "scripts/redact-network-diagnostics.py"
)
assert REDACTOR_SPEC and REDACTOR_SPEC.loader
REDACTOR = importlib.util.module_from_spec(REDACTOR_SPEC)
REDACTOR_SPEC.loader.exec_module(REDACTOR)


def command_record(returncode: int | None, stdout: str = "", stderr: str = "") -> dict:
    return {
        "exitCode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def sanitize_evidence(value):
    """Redact the complete string when it contains a credential marker."""
    if isinstance(value, dict):
        return {key: (REDACTOR.REDACTED if key in REDACTOR.FORBIDDEN_KEYS else sanitize_evidence(child)) for key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_evidence(child) for child in value]
    if isinstance(value, str) and REDACTOR.SECRET_TEXT.search(value):
        return REDACTOR.REDACTED
    return value


def decoded_resource(record: dict) -> tuple[str, str | None]:
    if record["exitCode"] != 0:
        return "error", None
    text = record["stdout"].strip()
    if not text:
        return "absent", None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return "malformed", None
    uid = value.get("metadata", {}).get("uid") if isinstance(value, dict) else None
    if not isinstance(uid, str) or not uid:
        return "malformed", None
    return "present", uid


def delete_error_category(record: dict) -> str:
    text = (record["stdout"] + "\n" + record["stderr"]).lower()
    if "forbidden" in text or "unauthorized" in text:
        return "authorization_error"
    if "timed out" in text or "deadline exceeded" in text:
        return "deletion_timeout"
    if any(marker in text for marker in ("unable to connect", "connection refused", "tls handshake timeout", "i/o timeout")):
        return "api_connectivity_error"
    if "notfound" in text or "not found" in text:
        return "not_found_race"
    return "delete_command_error"


def evaluate(original_uid: str, before: dict, deletion: dict, after: dict) -> tuple[str, bool, str | None]:
    before_state, before_uid = decoded_resource(before)
    if before_state == "error":
        return "pre_delete_get_error", False, None
    if before_state == "malformed":
        return "malformed_pre_delete_get", False, None
    if before_state == "absent":
        return "already_absent", True, None
    if before_uid != original_uid:
        return "name_reused", False, before_uid

    after_state, after_uid = decoded_resource(after)
    if after_state == "error":
        return "final_get_error", False, None
    if after_state == "malformed":
        return "malformed_final_get", False, None
    if after_state == "present":
        if after_uid == original_uid:
            return "original_uid_still_present", False, after_uid
        return "name_reused", False, after_uid
    if deletion["exitCode"] == 0:
        return "deleted", True, None
    category = delete_error_category(deletion)
    if category == "not_found_race":
        return "already_absent_after_race", True, None
    return category, False, None


def combined_exit(assertion_exit: int, cleanup_ok: bool) -> int:
    if assertion_exit != 0:
        return assertion_exit
    return 0 if cleanup_ok else 1


def run_command(arguments: list[str]) -> dict:
    completed = subprocess.run(arguments, text=True, capture_output=True, check=False)
    return command_record(completed.returncode, completed.stdout, completed.stderr)


def cleanup(args: argparse.Namespace) -> int:
    started = time.monotonic()
    base = [args.kubectl, "--context", args.context]
    get = base + ["get", args.kind, args.name, "--namespace", args.namespace, "--ignore-not-found", "-o", "json"]
    before = run_command(get)
    before_state, before_uid = decoded_resource(before)
    deletion = command_record(None)
    after = before
    if before_state == "present" and before_uid == args.uid:
        deletion = run_command(base + [
            "delete", args.kind, args.name, "--namespace", args.namespace,
            "--wait=true", f"--timeout={args.timeout_seconds}s",
        ])
        after = run_command(get)
    result, success, final_uid = evaluate(args.uid, before, deletion, after)
    evidence = {
        "schemaVersion": 1,
        "resource": {"kind": args.kind, "namespace": args.namespace, "name": args.name, "originalUID": args.uid},
        "deleteCommand": deletion,
        "preDeleteGet": before,
        "finalGet": after,
        "finalUID": final_uid,
        "durationSeconds": round(time.monotonic() - started, 3),
        "cleanupResult": result,
        "success": success,
    }
    sanitized = sanitize_evidence(evidence)
    args.output.write_text(json.dumps(sanitized, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    REDACTOR.inspect(sanitized)
    print(json.dumps({"kind": args.kind, "namespace": args.namespace, "name": args.name, "cleanupResult": result, "success": success}, sort_keys=True))
    return 0 if success else 1


def self_test() -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    other = "22222222-2222-2222-2222-222222222222"
    present = command_record(0, json.dumps({"metadata": {"uid": uid}}))
    reused = command_record(0, json.dumps({"metadata": {"uid": other}}))
    absent = command_record(0, "")
    success = command_record(0, "deleted\n", "")
    cases = [
        ("deleted", True, present, success, absent),
        ("already_absent_after_race", True, present, command_record(1, "", "Error from server (NotFound): not found"), absent),
        ("original_uid_still_present", False, present, command_record(1, "", "failure"), present),
        ("name_reused", False, reused, command_record(None), reused),
        ("authorization_error", False, present, command_record(1, "", "Error from server (Forbidden)"), absent),
        ("api_connectivity_error", False, present, command_record(1, "", "Unable to connect to the server"), absent),
        ("deletion_timeout", False, present, command_record(1, "", "timed out waiting for condition"), absent),
        ("malformed_final_get", False, present, success, command_record(0, "not-json")),
        ("already_absent", True, absent, command_record(None), absent),
    ]
    for expected_result, expected_ok, before, deletion, after in cases:
        result, ok, _ = evaluate(uid, before, deletion, after)
        assert (result, ok) == (expected_result, expected_ok), (result, ok)
    assert combined_exit(7, True) == 7
    assert combined_exit(7, False) == 7
    assert combined_exit(0, False) == 1
    assert combined_exit(0, True) == 0
    evidence = {"deleteCommand": command_record(1, "visible stdout", "Authorization: Bearer secret-token")}
    sanitized = sanitize_evidence(evidence)
    assert "visible stdout" in sanitized["deleteCommand"]["stdout"]
    assert "secret-token" not in sanitized["deleteCommand"]["stderr"]
    REDACTOR.inspect(sanitized)
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "cleanup.json"
        path.write_text(json.dumps(sanitized), encoding="utf-8")
        assert path.is_file()
    print("PASS  observable cleanup classifies deletion, races, UID reuse, RBAC, connectivity, timeout, malformed responses, idempotence, combined exits, and sanitized command evidence.")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--kubectl", default="kubectl")
    cleanup_parser.add_argument("--context", required=True)
    cleanup_parser.add_argument("--kind", required=True)
    cleanup_parser.add_argument("--namespace", required=True)
    cleanup_parser.add_argument("--name", required=True)
    cleanup_parser.add_argument("--uid", required=True)
    cleanup_parser.add_argument("--timeout-seconds", type=int, default=20)
    cleanup_parser.add_argument("--output", type=pathlib.Path, required=True)
    subparsers.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    return cleanup(args)


if __name__ == "__main__":
    raise SystemExit(main())
