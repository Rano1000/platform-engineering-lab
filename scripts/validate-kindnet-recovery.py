#!/usr/bin/env python3
"""Validate immutable kindnet recovery identities without broad selectors or retries."""

import argparse
import hashlib
import json
import os
import pathlib
import re


EXPECTED_SELECTOR = {"matchLabels": {"app": "kindnet"}}
REQUIRED_TEMPLATE_LABELS = {"app": "kindnet", "k8s-app": "kindnet"}
EXPECTED_NODES = (
    "platform-engineering-lab-control-plane",
    "platform-engineering-lab-worker",
    "platform-engineering-lab-worker2",
)
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


def fail(message):
    raise ValueError(message)


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def ordered_pods(value):
    items = value.get("items", value) if isinstance(value, dict) else value
    by_node = {}
    for pod in items:
        node = pod.get("spec", {}).get("nodeName")
        if node in by_node:
            fail(f"multiple kindnet Pods exist on node {node}")
        by_node[node] = pod
    if set(by_node) != set(EXPECTED_NODES):
        fail(f"kindnet Pod nodes differ from the expected nodes: {sorted(by_node)}")
    return [by_node[node] for node in EXPECTED_NODES]


def validate_daemonset(daemonset, image):
    metadata = daemonset.get("metadata", {})
    if (metadata.get("name"), metadata.get("namespace")) != ("kindnet", "kube-system"):
        fail("kindnet DaemonSet identity is unexpected")
    selector = daemonset.get("spec", {}).get("selector")
    if selector != EXPECTED_SELECTOR:
        fail(f"kindnet DaemonSet selector must equal {EXPECTED_SELECTOR}")
    labels = daemonset["spec"].get("template", {}).get("metadata", {}).get("labels", {})
    if any(labels.get(key) != value for key, value in REQUIRED_TEMPLATE_LABELS.items()):
        fail("kindnet Pod template does not contain the required app and k8s-app labels")
    containers = daemonset["spec"]["template"].get("spec", {}).get("containers", [])
    if len(containers) != 1 or containers[0].get("image") != image:
        fail("kindnet DaemonSet image differs from the pinned identity")
    status = daemonset.get("status", {})
    if any(status.get(key) != 3 for key in ("desiredNumberScheduled", "currentNumberScheduled", "numberReady")):
        fail("kindnet DaemonSet must be desired/current/Ready 3/3/3")
    if not metadata.get("uid") or not isinstance(metadata.get("generation"), int):
        fail("kindnet DaemonSet UID or generation is missing")


def validate_pod(pod, daemonset_uid, image, expected_node=None):
    metadata, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
    node = spec.get("nodeName")
    if expected_node is not None and node != expected_node:
        fail(f"kindnet Pod placement changed from {expected_node} to {node}")
    if any(metadata.get("labels", {}).get(key) != value for key, value in EXPECTED_SELECTOR["matchLabels"].items()):
        fail("kindnet Pod does not match the exact DaemonSet selector")
    owners = [owner for owner in metadata.get("ownerReferences", []) if owner.get("controller") is True]
    if len(owners) != 1 or (
        owners[0].get("apiVersion"), owners[0].get("kind"), owners[0].get("name"), owners[0].get("uid")
    ) != ("apps/v1", "DaemonSet", "kindnet", daemonset_uid):
        fail("kindnet Pod is not directly controlled by the exact DaemonSet UID")
    containers = spec.get("containers", [])
    statuses = status.get("containerStatuses", [])
    if len(containers) != 1 or containers[0].get("image") != image:
        fail("kindnet Pod image differs from the pinned identity")
    if status.get("phase") != "Running" or len(statuses) != 1 or statuses[0].get("ready") is not True:
        fail("kindnet Pod is not Running and Ready")
    if statuses[0].get("image") != image or not IMAGE_ID.fullmatch(statuses[0].get("imageID", "")):
        fail("kindnet Pod runtime image identity is incomplete or unexpected")
    if not metadata.get("name") or not metadata.get("uid"):
        fail("kindnet Pod name or UID is missing")
    return {
        "name": metadata["name"], "uid": metadata["uid"], "node": node,
        "ownerUID": daemonset_uid, "image": image, "runtimeImageID": statuses[0]["imageID"],
        "restartCount": statuses[0].get("restartCount", 0),
    }


def identity(daemonset, items, image):
    validate_daemonset(daemonset, image)
    daemonset_uid = daemonset["metadata"]["uid"]
    validated = [
        validate_pod(pod, daemonset_uid, image, node)
        for node, pod in zip(EXPECTED_NODES, ordered_pods(items))
    ]
    return {
        "schemaVersion": 1, "selector": EXPECTED_SELECTOR,
        "requiredTemplateLabels": REQUIRED_TEMPLATE_LABELS,
        "daemonSet": {
            "uid": daemonset_uid, "generation": daemonset["metadata"]["generation"], "image": image,
        },
        "pods": validated,
    }


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    command = subparsers.add_parser("preflight")
    command.add_argument("--daemonset"); command.add_argument("--pods"); command.add_argument("--image"); command.add_argument("--output")
    command = subparsers.add_parser("confirmation")
    command.add_argument("--identity"); command.add_argument("--context")
    command = subparsers.add_parser("plan"); command.add_argument("--identity")
    command = subparsers.add_parser("unchanged")
    command.add_argument("--identity"); command.add_argument("--daemonset"); command.add_argument("--pod")
    command.add_argument("--node"); command.add_argument("--uid")
    command = subparsers.add_parser("replacement")
    command.add_argument("--pods"); command.add_argument("--node"); command.add_argument("--old-name")
    command.add_argument("--old-uid"); command.add_argument("--image"); command.add_argument("--daemonset-uid")
    command = subparsers.add_parser("manifest"); command.add_argument("--root")
    args = parser.parse_args()
    try:
        if args.cmd == "preflight":
            value = identity(load(args.daemonset), load(args.pods)["items"], args.image)
            pathlib.Path(args.output).write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
            return
        value = load(args.identity) if hasattr(args, "identity") else None
        if args.cmd == "confirmation":
            print(args.context + "/kindnet/" + value["daemonSet"]["uid"] + "/" + ",".join(item["uid"] for item in value["pods"]))
            return
        if args.cmd == "plan":
            for item in value["pods"]:
                print("|".join((item["node"], item["name"], item["uid"])))
            return
        if args.cmd == "unchanged":
            daemonset, pod = load(args.daemonset), load(args.pod)
            validate_daemonset(daemonset, value["daemonSet"]["image"])
            if daemonset["metadata"]["uid"] != value["daemonSet"]["uid"] or daemonset["metadata"]["generation"] != value["daemonSet"]["generation"]:
                fail("kindnet DaemonSet identity changed after confirmation")
            current = validate_pod(pod, value["daemonSet"]["uid"], value["daemonSet"]["image"], args.node)
            if current["uid"] != args.uid:
                fail("kindnet Pod UID changed after confirmation")
            return
        if args.cmd == "replacement":
            items = load(args.pods).get("items", [])
            if len(items) != 1:
                fail("replacement query must return exactly one Pod")
            current = validate_pod(items[0], args.daemonset_uid, args.image, args.node)
            if current["uid"] == args.old_uid or current["name"] == args.old_name:
                fail("kindnet replacement retained the original name or UID")
            return
        root = pathlib.Path(args.root)
        files = {}
        for path in sorted(root.rglob("*")):
            if path.name == "evidence-manifest.json":
                continue
            if path.is_symlink() or (not path.is_dir() and not path.is_file()):
                fail(f"unsafe recovery evidence entry: {path}")
            if path.is_file():
                files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        temporary = root / ".manifest.tmp"
        temporary.write_text(json.dumps({"schemaVersion": 1, "files": files}, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(temporary, root / "evidence-manifest.json")
    except (AssertionError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR {error}") from error


if __name__ == "__main__":
    main()
