#!/usr/bin/env python3
"""Validate and checksum the repository-owned deny-all default AppProject."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib

import yaml

EXPECTED_NAME = "default"
EXPECTED_NAMESPACE = "gitops"
OWNERSHIP_LABELS = {
    "app.kubernetes.io/component": "project-guard",
    "app.kubernetes.io/managed-by": "platform-engineering-lab",
    "app.kubernetes.io/part-of": "argocd",
    "platform.engineering-lab/owner": "platform-team",
}
OWNERSHIP_ANNOTATIONS = {
    "platform.engineering-lab/purpose": "deny-all-default-project",
}
DENY_SPEC = {
    "description": "Deny-all default project; applications must use a dedicated project.",
    "sourceRepos": [],
    "destinations": [],
    "clusterResourceWhitelist": [],
    "namespaceResourceWhitelist": [],
}


def load(path: pathlib.Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def protected(value: dict) -> dict:
    metadata = value.get("metadata", {})
    return {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "metadata": {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "labels": metadata.get("labels", {}),
            "annotations": metadata.get("annotations", {}),
        },
        "spec": value.get("spec", {}),
    }


def checksum(value: dict) -> str:
    encoded = json.dumps(protected(value), sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_expected(value: dict) -> None:
    identity = protected(value)
    assert identity["apiVersion"] == "argoproj.io/v1alpha1"
    assert identity["kind"] == "AppProject"
    assert identity["metadata"] == {
        "name": EXPECTED_NAME,
        "namespace": EXPECTED_NAMESPACE,
        "labels": OWNERSHIP_LABELS,
        "annotations": OWNERSHIP_ANNOTATIONS,
    }
    assert identity["spec"] == DENY_SPEC
    encoded = json.dumps(identity, sort_keys=True)
    assert '"*"' not in encoded


def validate_live(expected: dict, live: dict) -> str:
    validate_expected(expected)
    actual = protected(live)
    required = protected(expected)
    if actual != required:
        raise ValueError("live default AppProject differs from the deny-all ownership and specification contract")
    return checksum(actual)


def validate_preflight(live: dict) -> None:
    metadata = live.get("metadata", {})
    if metadata.get("name") != EXPECTED_NAME or metadata.get("namespace") != EXPECTED_NAMESPACE:
        raise ValueError("unexpected default AppProject identity")
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})
    managed_by = labels.get("app.kubernetes.io/managed-by")
    owner = labels.get("platform.engineering-lab/owner")
    purpose = annotations.get("platform.engineering-lab/purpose")
    if managed_by not in (None, OWNERSHIP_LABELS["app.kubernetes.io/managed-by"]):
        raise ValueError("default AppProject has an unrelated manager")
    if owner not in (None, OWNERSHIP_LABELS["platform.engineering-lab/owner"]):
        raise ValueError("default AppProject has an unrelated owner")
    if purpose not in (None, OWNERSHIP_ANNOTATIONS["platform.engineering-lab/purpose"]):
        raise ValueError("default AppProject has an unrelated purpose")


def self_test() -> None:
    expected = {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "AppProject",
        "metadata": {"name": EXPECTED_NAME, "namespace": EXPECTED_NAMESPACE,
                     "labels": copy.deepcopy(OWNERSHIP_LABELS), "annotations": copy.deepcopy(OWNERSHIP_ANNOTATIONS)},
        "spec": copy.deepcopy(DENY_SPEC),
    }
    validate_expected(expected)
    assert validate_live(expected, copy.deepcopy(expected)) == checksum(expected)
    validate_preflight({"metadata": {"name": EXPECTED_NAME, "namespace": EXPECTED_NAMESPACE}})
    validate_preflight(copy.deepcopy(expected))
    for field, bad in (
        ("sourceRepos", ["*"]),
        ("destinations", [{"server": "*", "namespace": "*"}]),
        ("clusterResourceWhitelist", [{"group": "*", "kind": "*"}]),
        ("namespaceResourceWhitelist", [{"group": "*", "kind": "*"}]),
    ):
        invalid = copy.deepcopy(expected)
        invalid["spec"][field] = bad
        try:
            validate_expected(invalid)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"permissive {field} was accepted")
    reused = copy.deepcopy(expected)
    reused["metadata"]["labels"]["app.kubernetes.io/managed-by"] = "unrelated"
    try:
        validate_preflight(reused)
    except ValueError:
        pass
    else:
        raise AssertionError("unrelated ownership was accepted")
    print("PASS  default AppProject is deny-all, wildcard-free, repository-owned, and deterministically checksummed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected", type=pathlib.Path)
    parser.add_argument("--live", type=pathlib.Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.live:
        parser.error("--live is required")
    live = load(args.live) if args.live.suffix in {".yaml", ".yml"} else json.loads(args.live.read_text(encoding="utf-8"))
    if args.preflight:
        validate_preflight(live)
        print("PASS  default AppProject ownership may be adopted safely.")
        return 0
    if not args.expected:
        parser.error("--expected is required for complete validation")
    print(validate_live(load(args.expected), live))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
