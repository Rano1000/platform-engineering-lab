#!/usr/bin/env python3
"""Capture sanitized, read-only evidence after an Argo CD Helm failure."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("diagnostic_redactor", ROOT / "scripts/redact-network-diagnostics.py")
assert SPEC and SPEC.loader
REDACTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REDACTOR)


def sanitize(value):
    if isinstance(value, dict):
        return {key: sanitize(child) for key, child in value.items() if key not in REDACTOR.FORBIDDEN_KEYS}
    if isinstance(value, list):
        return [sanitize(child) for child in value]
    if isinstance(value, str) and REDACTOR.SECRET_TEXT.search(value):
        return REDACTOR.REDACTED
    return value


def run(arguments: list[str]) -> dict:
    completed = subprocess.run(arguments, text=True, capture_output=True, check=False)
    return {"command": arguments, "exitCode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def json_capture(arguments: list[str]) -> dict:
    record = run(arguments)
    text = record.pop("stdout")
    if text.strip():
        try:
            record["object"] = json.loads(text)
        except json.JSONDecodeError:
            record["malformedOutput"] = text
    return sanitize(record)


def pod_summary(pods: dict) -> list[dict]:
    items = pods.get("object", {}).get("items", [])
    summary = []
    for pod in items:
        status = pod.get("status", {})
        containers = []
        for container in status.get("containerStatuses", []):
            state = container.get("state", {})
            containers.append({
                "name": container.get("name"),
                "image": container.get("image"),
                "ready": container.get("ready"),
                "restartCount": container.get("restartCount"),
                "waitingReason": state.get("waiting", {}).get("reason"),
                "waitingMessage": state.get("waiting", {}).get("message"),
                "terminatedReason": state.get("terminated", {}).get("reason"),
            })
        summary.append({
            "name": pod.get("metadata", {}).get("name"),
            "uid": pod.get("metadata", {}).get("uid"),
            "node": pod.get("spec", {}).get("nodeName"),
            "phase": status.get("phase"),
            "podScheduled": next((item.get("status") for item in status.get("conditions", []) if item.get("type") == "PodScheduled"), None),
            "containers": containers,
        })
    return summary


def capture(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=False)
    kubectl = [args.kubectl, "--context", args.context]
    namespaced = kubectl + ["--namespace", args.namespace]
    records = {
        "pods": json_capture(namespaced + ["get", "pods", "-o", "json"]),
        "events": json_capture(namespaced + ["get", "events", "--sort-by=.metadata.creationTimestamp", "-o", "json"]),
        "workloads": json_capture(namespaced + ["get", "deployments,statefulsets,jobs", "-o", "json"]),
        "services": json_capture(namespaced + ["get", "services", "-o", "json"]),
        "hookServiceAccount": json_capture(namespaced + ["get", "serviceaccount", "argocd-redis-secret-init", "--ignore-not-found", "-o", "json"]),
        "hookRole": json_capture(namespaced + ["get", "role", "argocd-redis-secret-init", "--ignore-not-found", "-o", "json"]),
        "hookRoleBinding": json_capture(namespaced + ["get", "rolebinding", "argocd-redis-secret-init", "--ignore-not-found", "-o", "json"]),
        "redisSecretMetadata": json_capture(namespaced + ["get", "secret", "argocd-redis", "--ignore-not-found", "-o", "json"]),
        "crds": json_capture(kubectl + ["get", "crd", "applications.argoproj.io", "applicationsets.argoproj.io", "appprojects.argoproj.io", "--ignore-not-found", "-o", "json"]),
        "clusterRbac": json_capture(kubectl + ["get", "clusterroles,clusterrolebindings", "-l", "app.kubernetes.io/instance=argocd", "-o", "json"]),
        "helmStatus": sanitize(run([args.helm, "--kube-context", args.context, "--namespace", args.namespace, "status", args.release, "--show-resources"])),
    }
    secret = records["redisSecretMetadata"].get("object")
    if isinstance(secret, dict):
        secret.pop("data", None)
        secret.pop("stringData", None)
    summary = {
        "schemaVersion": 1,
        "context": args.context,
        "namespace": args.namespace,
        "release": args.release,
        "pods": pod_summary(records["pods"]),
        "workloadReadiness": records["workloads"].get("object", {}),
        "imagePullEvents": [
            item for item in records["events"].get("object", {}).get("items", [])
            if item.get("reason") in {"Scheduled", "Pulling", "Pulled", "Failed", "BackOff", "Unhealthy"}
        ],
    }
    for name, value in records.items():
        destination = args.output / f"{name}.json"
        destination.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        REDACTOR.inspect(value)
    (args.output / "summary.json").write_text(json.dumps(sanitize(summary), sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    REDACTOR.inspect(sanitize(summary))
    print(f"Argo installation failure diagnostics: {args.output}")
    return 0


def self_test() -> None:
    fixture = {"object": {"items": [{
        "metadata": {"name": "argocd-server", "uid": "uid-1"},
        "spec": {"nodeName": "worker"},
        "status": {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "True"}],
                   "containerStatuses": [{"name": "server", "image": "image@sha256:" + "a" * 64,
                                          "ready": False, "restartCount": 0,
                                          "state": {"waiting": {"reason": "ContainerCreating", "message": "pulling"}}}]},
    }]}}
    summary = pod_summary(fixture)
    assert summary[0]["node"] == "worker" and summary[0]["containers"][0]["waitingReason"] == "ContainerCreating"
    evidence = sanitize({"stderr": "Authorization: Bearer secret", "data": {"token": "secret"}})
    assert evidence == {"stderr": REDACTOR.REDACTED}
    REDACTOR.inspect(evidence)
    print("PASS  Argo installation failure diagnostics retain scheduling, pull, waiting, hook, readiness, Helm, CRD, and RBAC evidence without credentials.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--context")
    parser.add_argument("--namespace")
    parser.add_argument("--release")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.context, args.namespace, args.release, args.output)):
        parser.error("capture requires context, namespace, release, and output")
    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
