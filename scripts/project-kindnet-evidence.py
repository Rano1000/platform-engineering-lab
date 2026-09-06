#!/usr/bin/env python3
"""Create a minimal, credential-safe evidence projection for the pinned kindnet DaemonSet."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import stat
import tempfile


EXPECTED_IMAGE = "docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88"
EXPECTED_SELECTOR = {"matchLabels": {"app": "kindnet"}}
EXPECTED_TEMPLATE_LABELS = {"app": "kindnet", "k8s-app": "kindnet"}
EXPECTED_FIELD_REFS = {
    "HOST_IP": ("v1", "status.hostIP"),
    "POD_IP": ("v1", "status.podIP"),
}
# These are non-secret kindnet configuration, but literal environment values never enter evidence.
EXPECTED_OMITTED_LITERALS = {
    "POD_SUBNET": "10.244.0.0/16",
    "CONTROL_PLANE_ENDPOINT": "platform-engineering-lab-control-plane:6443",
}
SENSITIVE = re.compile(r"(?i)(authorization|bearer|credential|password|private.?key|secret|token)")


def fail(message: str) -> None:
    raise ValueError(message)


def exact_keys(value: object, keys: set[str], description: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"malformed {description}")
    return value


def validate_environment(container: dict) -> list[dict]:
    if "envFrom" in container:
        fail("kindnet envFrom is forbidden")
    entries = container.get("env")
    if not isinstance(entries, list):
        fail("kindnet environment entries are missing")
    by_name: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            fail("malformed kindnet environment entry")
        name = entry["name"]
        if name in by_name:
            fail("duplicate kindnet environment name")
        by_name[name] = entry
    expected = set(EXPECTED_FIELD_REFS) | set(EXPECTED_OMITTED_LITERALS)
    if set(by_name) != expected:
        fail("kindnet environment names differ from the pinned manifest")

    projected = []
    for name, (api_version, field_path) in EXPECTED_FIELD_REFS.items():
        entry = exact_keys(by_name[name], {"name", "valueFrom"}, f"{name} entry")
        value_from = exact_keys(entry["valueFrom"], {"fieldRef"}, f"{name} valueFrom")
        field_ref = exact_keys(value_from["fieldRef"], {"apiVersion", "fieldPath"}, f"{name} fieldRef")
        if (field_ref["apiVersion"], field_ref["fieldPath"]) != (api_version, field_path):
            fail(f"{name} downward-API fieldRef differs from the pinned manifest")
        projected.append({
            "name": name,
            "valueFrom": {"fieldRef": {"apiVersion": api_version, "fieldPath": field_path}},
        })

    for name, expected_value in EXPECTED_OMITTED_LITERALS.items():
        entry = exact_keys(by_name[name], {"name", "value"}, f"{name} source entry")
        value = entry["value"]
        if not isinstance(value, str) or value != expected_value or SENSITIVE.search(value):
            fail(f"{name} literal differs from the pinned non-secret configuration")
    return projected


def project(value: object) -> dict:
    if not isinstance(value, dict):
        fail("kindnet DaemonSet must be an object")
    metadata = value.get("metadata", {})
    spec = value.get("spec", {})
    template = spec.get("template", {})
    pod_spec = template.get("spec", {})
    containers = pod_spec.get("containers", [])
    if (value.get("apiVersion"), value.get("kind"), metadata.get("namespace"), metadata.get("name")) != (
        "apps/v1", "DaemonSet", "kube-system", "kindnet"
    ):
        fail("kindnet DaemonSet identity is unexpected")
    if spec.get("selector") != EXPECTED_SELECTOR:
        fail("kindnet DaemonSet selector is unexpected")
    labels = template.get("metadata", {}).get("labels", {})
    if any(labels.get(key) != expected for key, expected in EXPECTED_TEMPLATE_LABELS.items()):
        fail("kindnet template labels are unexpected")
    if len(containers) != 1 or containers[0].get("name") != "kindnet-cni" or containers[0].get("image") != EXPECTED_IMAGE:
        fail("kindnet container identity is unexpected")
    fields = validate_environment(containers[0])
    uid, generation = metadata.get("uid"), metadata.get("generation")
    if not isinstance(uid, str) or not uid or not isinstance(generation, int):
        fail("kindnet UID or generation is missing")
    status = value.get("status", {})
    counts = {key: status.get(key) for key in ("desiredNumberScheduled", "currentNumberScheduled", "numberReady")}
    if any(not isinstance(item, int) for item in counts.values()):
        fail("kindnet readiness counts are malformed")
    return {
        "schemaVersion": 1,
        "daemonSet": {
            "apiVersion": "apps/v1", "kind": "DaemonSet", "namespace": "kube-system", "name": "kindnet",
            "uid": uid, "generation": generation, "selector": EXPECTED_SELECTOR,
            "templateLabels": EXPECTED_TEMPLATE_LABELS, "containerName": "kindnet-cni", "image": EXPECTED_IMAGE,
            "downwardAPIFields": fields,
            "omittedPinnedLiteralNames": sorted(EXPECTED_OMITTED_LITERALS),
            "status": counts,
        },
    }


def atomic_json(destination: pathlib.Path, value: dict) -> None:
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink() or destination.is_symlink():
        fail("unsafe kindnet evidence destination")
    if destination.exists() and not destination.is_file():
        fail("kindnet evidence destination is not a regular file")
    descriptor, raw = tempfile.mkstemp(prefix=f".{destination.name}.", dir=parent)
    temporary = pathlib.Path(raw)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        atomic_json(args.output, project(json.loads(args.source.read_text(encoding="utf-8"))))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as error:
        raise SystemExit(f"ERROR {error}") from error


if __name__ == "__main__":
    main()
