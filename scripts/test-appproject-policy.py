#!/usr/bin/env python3
"""Semantic regression tests for the two restricted GitOps AppProjects."""

from __future__ import annotations

import copy
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/Rano1000/platform-engineering-lab.git"
IN_CLUSTER = "https://kubernetes.default.svc"
BOOTSTRAP_KINDS = {("argoproj.io", "Application")}
WORKLOAD_KINDS = {
    ("", "ConfigMap"),
    ("", "Service"),
    ("", "ServiceAccount"),
    ("apps", "Deployment"),
    ("policy", "PodDisruptionBudget"),
    ("networking.k8s.io", "NetworkPolicy"),
    ("gateway.networking.k8s.io", "HTTPRoute"),
}
FORBIDDEN_CLUSTER_KINDS = {
    ("", "Namespace"),
    ("apiextensions.k8s.io", "CustomResourceDefinition"),
    ("rbac.authorization.k8s.io", "ClusterRole"),
    ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
    ("gateway.networking.k8s.io", "GatewayClass"),
}


def load(name: str) -> dict:
    return yaml.safe_load((ROOT / "environments/local/gitops" / name).read_text(encoding="utf-8"))


def entries(spec: dict, field: str) -> set[tuple[str, str]]:
    return {(item["group"], item["kind"]) for item in spec[field]}


def validate(project: dict, namespace: str, allowed: set[tuple[str, str]]) -> None:
    metadata = project["metadata"]
    spec = project["spec"]
    assert metadata["namespace"] == "gitops"
    assert metadata["labels"] == {"app.kubernetes.io/managed-by": "platform-engineering-lab"}
    assert spec["sourceRepos"] == [REPOSITORY]
    assert spec["destinations"] == [{"server": IN_CLUSTER, "namespace": namespace}]
    assert spec["clusterResourceWhitelist"] == []
    assert "clusterResourceBlacklist" not in spec
    assert entries(spec, "namespaceResourceWhitelist") == allowed
    assert "*" not in str({
        "sourceRepos": spec["sourceRepos"],
        "destinations": spec["destinations"],
        "clusterResourceWhitelist": spec["clusterResourceWhitelist"],
        "namespaceResourceWhitelist": spec["namespaceResourceWhitelist"],
    })


def permits(project: dict, group: str, kind: str, namespace: str, cluster_scoped: bool) -> bool:
    spec = project["spec"]
    if cluster_scoped:
        return (group, kind) in entries(spec, "clusterResourceWhitelist")
    destination = {"server": IN_CLUSTER, "namespace": namespace}
    return destination in spec["destinations"] and (group, kind) in entries(spec, "namespaceResourceWhitelist")


def rejected(project: dict, namespace: str, allowed: set[tuple[str, str]]) -> None:
    try:
        validate(project, namespace, allowed)
    except (AssertionError, KeyError, TypeError):
        return
    raise AssertionError("widened or incomplete AppProject policy was accepted")


def main() -> None:
    bootstrap = load("bootstrap-project.yaml")
    workload = load("workload-project.yaml")
    validate(bootstrap, "gitops", BOOTSTRAP_KINDS)
    validate(workload, "platform-apps", WORKLOAD_KINDS)
    assert permits(bootstrap, "argoproj.io", "Application", "gitops", False)
    assert all(permits(workload, group, kind, "platform-apps", False) for group, kind in WORKLOAD_KINDS)
    for project in (bootstrap, workload):
        assert all(not permits(project, group, kind, "", True) for group, kind in FORBIDDEN_CLUSTER_KINDS)
    for project, namespace, allowed in (
        (bootstrap, "gitops", BOOTSTRAP_KINDS),
        (workload, "platform-apps", WORKLOAD_KINDS),
    ):
        removed = copy.deepcopy(project)
        removed["spec"]["namespaceResourceWhitelist"].pop()
        rejected(removed, namespace, allowed)
        widened = copy.deepcopy(project)
        widened["spec"]["namespaceResourceWhitelist"].append({"group": "*", "kind": "*"})
        rejected(widened, namespace, allowed)
    widened_cluster = copy.deepcopy(bootstrap)
    widened_cluster["spec"]["clusterResourceWhitelist"] = [{"group": "*", "kind": "*"}]
    rejected(widened_cluster, "gitops", BOOTSTRAP_KINDS)
    print("PASS  AppProjects deny every cluster-scoped kind and permit only their exact namespaced resource sets.")


if __name__ == "__main__":
    main()
