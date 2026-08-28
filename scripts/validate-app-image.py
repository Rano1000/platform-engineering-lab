#!/usr/bin/env python3
"""Validate the deployed application's immutable image identity."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

LOCAL_TAG = re.compile(r"^0\.1\.0-([0-9a-f]{12})$")
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class IdentityError(ValueError):
    """The deployed image does not match its declared immutable identity."""


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_image(source: dict, source_kind: str) -> dict:
    if source_kind == "helm":
        return source.get("image", {})
    application = source
    image = application.get("spec", {}).get("source", {}).get("helm", {}).get("valuesObject", {}).get("image", {})
    annotations = application.get("metadata", {}).get("annotations", {})
    if annotations.get("platform.engineering-lab/image-source-revision") != image.get("revision"):
        raise IdentityError("Argo image revision differs from the protected Application annotation")
    if annotations.get("platform.engineering-lab/image-digest") != image.get("digest"):
        raise IdentityError("Argo image digest differs from the protected Application annotation")
    return image


def expected_identity(image: dict) -> tuple[str, str]:
    repository = image.get("repository", "")
    tag = image.get("tag", "") or ""
    digest = image.get("digest", "") or ""
    revision = image.get("revision", "")
    pull_policy = image.get("pullPolicy", "")
    if not SHA.fullmatch(revision):
        raise IdentityError("image revision must be a complete Git SHA")
    if tag == "latest" or repository.endswith(":latest"):
        raise IdentityError("latest is forbidden")
    if digest:
        if repository != "ghcr.io/rano1000/golden-path-api":
            raise IdentityError("digest deployment uses an unexpected repository")
        if tag or not DIGEST.fullmatch(digest):
            raise IdentityError("digest deployment must use one complete digest and no tag")
        if pull_policy != "IfNotPresent":
            raise IdentityError("digest deployment must use IfNotPresent")
        return f"{repository}@{digest}", "digest"
    match = LOCAL_TAG.fullmatch(tag)
    if repository != "golden-path-api" or not match:
        raise IdentityError("local deployment must use the approved immutable local tag")
    if match.group(1) != revision[:12]:
        raise IdentityError("local image tag does not match its full source revision")
    if pull_policy != "Never":
        raise IdentityError("local deployment must use imagePullPolicy Never")
    return f"{repository}:{tag}", "local"


def container(resource: dict, name: str = "api") -> dict:
    containers = resource.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    found = [item for item in containers if item.get("name") == name]
    if len(found) != 1:
        raise IdentityError(f"expected one {name} container in Deployment")
    return found[0]


def validate(source: dict, source_kind: str, deployment: dict, pods: dict, nodes: list[dict]) -> tuple[str, str]:
    expected, mode = expected_identity(source_image(source, source_kind))
    if container(deployment).get("image") != expected:
        raise IdentityError("Deployment image differs from approved identity")
    pod_items = pods.get("items", [])
    if not pod_items:
        raise IdentityError("no application Pods found")
    runtime_ids: set[str] = set()
    for pod in pod_items:
        pod_containers = pod.get("spec", {}).get("containers", [])
        specs = [item for item in pod_containers if item.get("name") == "api"]
        statuses = [item for item in pod.get("status", {}).get("containerStatuses", []) if item.get("name") == "api"]
        if len(specs) != 1 or specs[0].get("image") != expected:
            raise IdentityError("Pod image differs from approved identity")
        if len(statuses) != 1 or not statuses[0].get("imageID"):
            raise IdentityError("Pod runtime image ID is missing")
        runtime_ids.add(statuses[0]["imageID"])
    if len(runtime_ids) != 1:
        raise IdentityError("replicas run different image IDs")
    runtime_id = next(iter(runtime_ids))
    if mode == "digest":
        digest = expected.rsplit("@", 1)[1]
        if not runtime_id.endswith("@" + digest):
            raise IdentityError("runtime image ID differs from desired registry digest")
    else:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", runtime_id):
            raise IdentityError("local runtime image ID is not a complete content digest")
        if len(nodes) != 2:
            raise IdentityError("local image metadata is required from exactly two workers")
        accepted_tags = {expected, "docker.io/library/" + expected}
        for node in nodes:
            matches = [image for image in node.get("images", []) if accepted_tags.intersection(image.get("repoTags", []))]
            if len(matches) != 1:
                raise IdentityError("approved local image is missing or ambiguous on a worker")
            if matches[0].get("id") != runtime_id:
                raise IdentityError("worker image ID differs from the running Pod image ID")
    return expected, runtime_id


def self_test() -> None:
    revision = "a" * 40
    local = {"image": {"repository": "golden-path-api", "tag": "0.1.0-" + revision[:12], "digest": "", "revision": revision, "pullPolicy": "Never"}}
    local_ref = "golden-path-api:0.1.0-" + revision[:12]
    local_id = "sha256:" + "b" * 64
    deployment = {"spec": {"template": {"spec": {"containers": [{"name": "api", "image": local_ref}]}}}}
    pods = {"items": [{"spec": {"containers": [{"name": "api", "image": local_ref}]}, "status": {"containerStatuses": [{"name": "api", "imageID": local_id}]}}]}
    nodes = [{"images": [{"id": local_id, "repoTags": ["docker.io/library/" + local_ref]}]}] * 2
    validate(local, "helm", deployment, pods, nodes)

    digest = "sha256:" + "c" * 64
    registry_ref = "ghcr.io/rano1000/golden-path-api@" + digest
    image = {"repository": "ghcr.io/rano1000/golden-path-api", "tag": "", "digest": digest, "revision": revision, "pullPolicy": "IfNotPresent"}
    application = {"metadata": {"annotations": {"platform.engineering-lab/image-source-revision": revision, "platform.engineering-lab/image-digest": digest}}, "spec": {"source": {"helm": {"valuesObject": {"image": image}}}}}
    registry_deployment = {"spec": {"template": {"spec": {"containers": [{"name": "api", "image": registry_ref}]}}}}
    registry_pods = {"items": [{"spec": {"containers": [{"name": "api", "image": registry_ref}]}, "status": {"containerStatuses": [{"name": "api", "imageID": registry_ref}]}}]}
    validate(application, "argocd", registry_deployment, registry_pods, [])

    failures = []
    cases = [
        ({**local, "image": {**local["image"], "tag": "0.1.0-" + "d" * 12}}, "helm", deployment, pods, nodes),
        (application, "argocd", registry_deployment, {"items": [{"spec": {"containers": [{"name": "api", "image": registry_ref}]}, "status": {"containerStatuses": [{"name": "api", "imageID": "ghcr.io/rano1000/golden-path-api@sha256:" + "d" * 64}]}}]}, []),
        (local, "helm", deployment, pods, []),
        ({**local, "image": {**local["image"], "tag": "latest"}}, "helm", deployment, pods, nodes),
        ({**application, "metadata": {"annotations": {**application["metadata"]["annotations"], "platform.engineering-lab/image-source-revision": "d" * 40}}}, "argocd", registry_deployment, registry_pods, []),
    ]
    for case in cases:
        try:
            validate(*case)
        except IdentityError:
            failures.append(True)
    if len(failures) != len(cases):
        raise AssertionError("an invalid image identity was accepted")
    print("PASS  application image identity accepts immutable local and registry deployments and rejects mismatches, missing images, and latest.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-kind", choices=("helm", "argocd"))
    parser.add_argument("--source", type=pathlib.Path)
    parser.add_argument("--deployment", type=pathlib.Path)
    parser.add_argument("--pods", type=pathlib.Path)
    parser.add_argument("--node-images", action="append", default=[], type=pathlib.Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not all((args.source_kind, args.source, args.deployment, args.pods)):
        parser.error("runtime validation requires source kind, source, Deployment, and Pods")
    try:
        expected, runtime_id = validate(load(args.source), args.source_kind, load(args.deployment), load(args.pods), [load(path) for path in args.node_images])
    except IdentityError as error:
        print(f"FAIL  {error}.", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"PASS  deployed image {expected} has runtime identity {runtime_id}.")


if __name__ == "__main__":
    main()
