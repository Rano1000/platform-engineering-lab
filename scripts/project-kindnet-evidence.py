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
ALLOWED_POD_LABELS = {"app", "k8s-app", "tier", "controller-revision-hash", "pod-template-generation"}
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


def validate_pod_source_safety(pod_spec: dict) -> None:
    if pod_spec.get("initContainers") or pod_spec.get("ephemeralContainers"):
        fail("kindnet Pod has unexpected additional containers")
    volumes = pod_spec.get("volumes", [])
    if not isinstance(volumes, list):
        fail("kindnet Pod volumes are malformed")
    expected_host_paths = {"cni-cfg", "xtables-lock", "lib-modules", "nri-plugin"}
    host_paths = set()
    projected = []
    for volume in volumes:
        if not isinstance(volume, dict) or not isinstance(volume.get("name"), str):
            fail("kindnet Pod volume is malformed")
        keys = set(volume) - {"name"}
        if keys == {"hostPath"}:
            host_paths.add(volume["name"])
        elif keys == {"projected"} and re.fullmatch(r"kube-api-access-[a-z0-9]{5}", volume["name"]):
            projected.append(volume)
        else:
            fail("kindnet Pod contains an unexpected volume or reference")
    if host_paths != expected_host_paths or len(projected) != 1:
        fail("kindnet Pod volume identities differ from the pinned workload")
    # The bound service-account projection is expected in the raw Kubernetes Pod, but no
    # volume structure or projected credential metadata is copied into retained evidence.
    sources = projected[0]["projected"].get("sources") if isinstance(projected[0]["projected"], dict) else None
    if not isinstance(sources, list) or len(sources) != 3:
        fail("kindnet Pod service-account projection is malformed")
    source_types = []
    for source in sources:
        if not isinstance(source, dict) or len(source) != 1:
            fail("kindnet Pod projected source is malformed")
        source_types.extend(source)
    if sorted(source_types) != ["configMap", "downwardAPI", "serviceAccountToken"]:
        fail("kindnet Pod projected credential sources differ from Kubernetes defaults")


def project_daemonset(value: object) -> dict:
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
        "schemaVersion": 1, "projectionType": "kindnet-daemonset",
        "daemonSet": {
            "apiVersion": "apps/v1", "kind": "DaemonSet", "namespace": "kube-system", "name": "kindnet",
            "uid": uid, "generation": generation, "selector": EXPECTED_SELECTOR,
            "templateLabels": EXPECTED_TEMPLATE_LABELS, "containerName": "kindnet-cni", "image": EXPECTED_IMAGE,
            "downwardAPIFields": fields,
            "omittedPinnedLiteralNames": sorted(EXPECTED_OMITTED_LITERALS),
            "status": counts,
        },
    }


def safe_timestamp(value: object, description: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        fail(f"{description} is malformed")
    return value


def project_pod(value: object) -> dict:
    if not isinstance(value, dict) or (value.get("apiVersion"), value.get("kind")) != ("v1", "Pod"):
        fail("kindnet Pod identity is malformed")
    metadata, spec, status = value.get("metadata", {}), value.get("spec", {}), value.get("status", {})
    labels = metadata.get("labels", {})
    if not isinstance(labels, dict) or not set(labels).issubset(ALLOWED_POD_LABELS):
        fail("kindnet Pod labels contain an unexpected identity")
    if any(labels.get(key) != expected for key, expected in EXPECTED_TEMPLATE_LABELS.items()):
        fail("kindnet Pod required labels differ")
    if labels.get("tier") != "node" or not isinstance(labels.get("controller-revision-hash"), str):
        fail("kindnet Pod controller labels are incomplete")
    if not re.fullmatch(r"\d+", str(labels.get("pod-template-generation", ""))):
        fail("kindnet Pod template generation label is malformed")
    owners = metadata.get("ownerReferences", [])
    if len(owners) != 1 or set(owners[0]) - {"apiVersion", "kind", "name", "uid", "controller", "blockOwnerDeletion"}:
        fail("kindnet Pod owner reference is malformed")
    owner = owners[0]
    if (owner.get("apiVersion"), owner.get("kind"), owner.get("name"), owner.get("controller")) != (
        "apps/v1", "DaemonSet", "kindnet", True
    ) or not isinstance(owner.get("uid"), str):
        fail("kindnet Pod is not directly owned by kindnet")
    validate_pod_source_safety(spec)
    containers, statuses = spec.get("containers", []), status.get("containerStatuses", [])
    if len(containers) != 1 or len(statuses) != 1:
        fail("kindnet Pod must contain exactly one container and status")
    container, container_status = containers[0], statuses[0]
    if container.get("name") != "kindnet-cni" or container.get("image") != EXPECTED_IMAGE:
        fail("kindnet Pod container identity differs")
    fields = validate_environment(container)
    if container_status.get("name") != "kindnet-cni" or container_status.get("image") != EXPECTED_IMAGE:
        fail("kindnet Pod runtime container identity differs")
    runtime_image = container_status.get("imageID")
    if not isinstance(runtime_image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", runtime_image):
        fail("kindnet Pod runtime image ID is incomplete")
    ready_conditions = [item for item in status.get("conditions", []) if item.get("type") == "Ready"]
    if len(ready_conditions) != 1 or ready_conditions[0].get("status") not in {"True", "False"}:
        fail("kindnet Pod Ready condition is malformed")
    state = container_status.get("state", {})
    termination = None
    if "terminated" in state:
        terminated = state["terminated"]
        if not isinstance(terminated, dict) or not isinstance(terminated.get("reason"), str) or not isinstance(terminated.get("exitCode"), int):
            fail("kindnet Pod termination state is malformed")
        termination = {"reason": terminated["reason"], "exitCode": terminated["exitCode"]}
    elif set(state) != {"running"}:
        fail("kindnet Pod container state is unexpected")
    approved_labels = {key: labels[key] for key in sorted(labels)}
    return {
        "schemaVersion": 1, "projectionType": "kindnet-pod",
        "pod": {
            "metadata": {
                "name": metadata.get("name"), "namespace": metadata.get("namespace"), "uid": metadata.get("uid"),
                "labels": approved_labels,
                "ownerReference": {key: owner[key] for key in ("apiVersion", "kind", "name", "uid", "controller")},
                "creationTimestamp": safe_timestamp(metadata.get("creationTimestamp"), "Pod creation timestamp"),
            },
            "nodeName": spec.get("nodeName"), "phase": status.get("phase"),
            "readyCondition": ready_conditions[0]["status"] == "True",
            "startTime": safe_timestamp(status.get("startTime"), "Pod start timestamp"),
            "container": {
                "name": "kindnet-cni", "image": EXPECTED_IMAGE, "runtimeImageID": runtime_image,
                "ready": container_status.get("ready"), "restartCount": container_status.get("restartCount"),
                "termination": termination,
            },
            "downwardAPIFields": fields,
            "omittedPinnedLiteralNames": sorted(EXPECTED_OMITTED_LITERALS),
        },
    }


def project(value: object) -> dict:
    if isinstance(value, dict) and value.get("kind") == "DaemonSet":
        return project_daemonset(value)
    if isinstance(value, dict) and value.get("kind") == "Pod":
        return project_pod(value)
    if isinstance(value, dict) and value.get("kind") in {"PodList", "List"}:
        items = value.get("items")
        if not isinstance(items, list) or not items:
            fail("kindnet PodList is empty or malformed")
        projected = [project_pod(item)["pod"] for item in items]
        names = [item["metadata"]["name"] for item in projected]
        if len(names) != len(set(names)):
            fail("kindnet PodList contains duplicate names")
        return {"schemaVersion": 1, "projectionType": "kindnet-pod-list", "items": projected}
    fail("unsupported kindnet workload object")


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
