#!/usr/bin/env python3
"""Validate an Argo workload controller and every selected Pod."""

import argparse
import json


BAD_WAITING = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"}


def validate(workload: dict, pods: dict, previous_pods: dict | None = None) -> None:
    metadata, spec, status = workload.get("metadata", {}), workload.get("spec", {}), workload.get("status", {})
    desired = spec.get("replicas", 1)
    if not isinstance(desired, int) or desired < 0:
        raise ValueError("desired replica count is invalid")
    if status.get("observedGeneration") != metadata.get("generation"):
        raise ValueError("workload observedGeneration is stale")
    for field in ("updatedReplicas", "availableReplicas", "readyReplicas"):
        actual = status.get(field, 0)
        if actual != desired:
            raise ValueError(f"workload {field} is {actual}; expected {desired}")
    selected = pods.get("items", [])
    if len(selected) != desired:
        raise ValueError(f"selected Pod count is {len(selected)}; expected {desired}")
    for pod in selected:
        name = pod.get("metadata", {}).get("name", "unknown")
        phase = pod.get("status", {}).get("phase")
        if phase != "Running":
            raise ValueError(f"Pod {name} phase is {phase}")
        statuses = pod.get("status", {}).get("containerStatuses", [])
        expected_containers = len(pod.get("spec", {}).get("containers", []))
        if len(statuses) != expected_containers or not statuses:
            raise ValueError(f"Pod {name} container status is incomplete")
        for container in statuses:
            waiting = container.get("state", {}).get("waiting", {}).get("reason")
            if waiting in BAD_WAITING:
                raise ValueError(f"Pod {name} container {container.get('name')} is {waiting}")
            if not container.get("ready"):
                raise ValueError(f"Pod {name} container {container.get('name')} is unready")
    if previous_pods is not None:
        previous = {(pod["metadata"]["uid"], status["name"]): status.get("restartCount", 0) for pod in previous_pods.get("items", []) for status in pod.get("status", {}).get("containerStatuses", [])}
        for pod in selected:
            for container in pod.get("status", {}).get("containerStatuses", []):
                key = (pod["metadata"]["uid"], container["name"])
                if key not in previous or container.get("restartCount", 0) > previous[key]:
                    raise ValueError(f"Pod {pod['metadata']['name']} has unexpected restart growth")


def fixture() -> tuple[dict, dict]:
    workload = {"metadata": {"name": "argocd-repo-server", "generation": 3}, "spec": {"replicas": 1}, "status": {"observedGeneration": 3, "updatedReplicas": 1, "availableReplicas": 1, "readyReplicas": 1}}
    pods = {"items": [{"metadata": {"name": "repo-1"}, "spec": {"containers": [{"name": "repo-server"}]}, "status": {"phase": "Running", "containerStatuses": [{"name": "repo-server", "ready": True, "restartCount": 0, "state": {"running": {}}}]}}]}
    return workload, pods


def rejected(workload: dict, pods: dict) -> None:
    try:
        validate(workload, pods)
    except ValueError:
        return
    raise AssertionError("invalid workload state passed")


def self_test() -> None:
    workload, pods = fixture(); validate(workload, pods)
    crash = json.loads(json.dumps(pods)); crash["items"][0]["status"]["containerStatuses"][0].update({"ready": False, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}); rejected(workload, crash)
    stale = json.loads(json.dumps(workload)); stale["status"]["observedGeneration"] = 2; rejected(stale, pods)
    for field in ("updatedReplicas", "availableReplicas", "readyReplicas"):
        insufficient = json.loads(json.dumps(workload)); insufficient["status"][field] = 0; rejected(insufficient, pods)
    pending = json.loads(json.dumps(pods)); pending["items"][0]["status"]["phase"] = "Pending"; rejected(workload, pending)
    previous = json.loads(json.dumps(pods)); previous["items"][0]["metadata"]["uid"] = "pod-uid"; pods["items"][0]["metadata"]["uid"] = "pod-uid"
    restarted = json.loads(json.dumps(pods)); restarted["items"][0]["status"]["containerStatuses"][0]["restartCount"] = 1
    try: validate(workload, restarted, previous)
    except ValueError: pass
    else: raise AssertionError("restart growth passed")
    print("PASS  Argo workload readiness rejects stale controllers, unready Pods, pull failures, crash loops, and restart growth.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload"); parser.add_argument("--pods"); parser.add_argument("--previous-pods"); parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test: self_test(); return
    if not args.workload or not args.pods: parser.error("--workload and --pods are required")
    try:
        previous = json.load(open(args.previous_pods, encoding="utf-8")) if args.previous_pods else None
        validate(json.load(open(args.workload, encoding="utf-8")), json.load(open(args.pods, encoding="utf-8")), previous)
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit("FAIL  " + str(error)) from error
    print("PASS  workload and selected Pods are Ready.")


if __name__ == "__main__":
    main()
