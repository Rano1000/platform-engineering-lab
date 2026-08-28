#!/usr/bin/env python3
"""Classify an optional Argo Application lookup without hiding API failures."""

from __future__ import annotations

import argparse
import json
import subprocess


def record(command: list[str]) -> dict:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    return {"exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def error_state(value: dict) -> str:
    text = (value["stdout"] + "\n" + value["stderr"]).lower()
    if "forbidden" in text or "unauthorized" in text:
        return "authorization_error"
    if any(marker in text for marker in ("unable to connect", "connection refused", "i/o timeout", "tls handshake timeout")):
        return "api_error"
    return "api_error"


def classify(crd: dict, application: dict, expected_name: str) -> str:
    if crd["exitCode"] != 0:
        return error_state(crd)
    if not crd["stdout"].strip():
        return "crd_unavailable"
    if application["exitCode"] != 0:
        return error_state(application)
    text = application["stdout"].strip()
    if not text:
        return "absent"
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return "parsing_error"
    if value.get("kind") != "Application" or value.get("metadata", {}).get("name") != expected_name:
        return "parsing_error"
    return "present"


def probe(args: argparse.Namespace) -> int:
    base = [args.kubectl, "--context", args.context]
    crd = record(base + ["get", "crd", "applications.argoproj.io", "--ignore-not-found", "-o", "name"])
    application = record(base + ["get", "application.argoproj.io", args.name, "--namespace", args.namespace,
                                 "--ignore-not-found", "-o", "json"])
    state = classify(crd, application, args.name)
    print(state)
    return 0 if state in {"absent", "present"} else 1


def self_test() -> None:
    ok_crd = {"exitCode": 0, "stdout": "customresourcedefinition.apiextensions.k8s.io/applications.argoproj.io\n", "stderr": ""}
    absent = {"exitCode": 0, "stdout": "", "stderr": ""}
    present = {"exitCode": 0, "stdout": json.dumps({"kind": "Application", "metadata": {"name": "golden-path-api"}}), "stderr": ""}
    assert classify(absent, absent, "golden-path-api") == "crd_unavailable"
    assert classify(ok_crd, absent, "golden-path-api") == "absent"
    assert classify(ok_crd, present, "golden-path-api") == "present"
    assert classify({"exitCode": 1, "stdout": "", "stderr": "Forbidden"}, absent, "golden-path-api") == "authorization_error"
    assert classify(ok_crd, {"exitCode": 1, "stdout": "", "stderr": "Unable to connect to the server"}, "golden-path-api") == "api_error"
    assert classify(ok_crd, {"exitCode": 0, "stdout": "not-json", "stderr": ""}, "golden-path-api") == "parsing_error"
    wrong = {"exitCode": 0, "stdout": json.dumps({"kind": "Application", "metadata": {"name": "other"}}), "stderr": ""}
    assert classify(ok_crd, wrong, "golden-path-api") == "parsing_error"
    print("PASS  optional Application lookup distinguishes CRD absence, expected absence, presence, authorization, API, and parsing failures.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--context")
    parser.add_argument("--namespace")
    parser.add_argument("--name")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.context, args.namespace, args.name)):
        parser.error("probe requires context, namespace, and name")
    return probe(args)


if __name__ == "__main__":
    raise SystemExit(main())
