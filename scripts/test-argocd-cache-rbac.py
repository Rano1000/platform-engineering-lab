#!/usr/bin/env python3
"""Validate the complete bounded Argo application-controller RBAC contract."""

from __future__ import annotations

import copy
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
READ = {"get", "list", "watch"}
MANAGE = READ | {"create", "update", "patch", "delete"}
EVENTS = READ | {"create", "patch"}
EXPECTED = {
    (("",), ("configmaps", "services", "serviceaccounts")): MANAGE,
    (("apps",), ("deployments",)): MANAGE,
    (("policy",), ("poddisruptionbudgets",)): MANAGE,
    (("networking.k8s.io",), ("networkpolicies",)): MANAGE,
    (("gateway.networking.k8s.io",), ("httproutes",)): MANAGE,
    (("",), ("namespaces", "pods")): READ,
    (("",), ("events",)): EVENTS,
    (("apps",), ("replicasets",)): READ,
    (("discovery.k8s.io",), ("endpointslices",)): READ,
}
FORBIDDEN_RESOURCES = {
    "secrets",
    "validatingwebhookconfigurations",
    "mutatingwebhookconfigurations",
    "selfsubjectaccessreviews",
}
FORBIDDEN_VERBS = {"impersonate", "bind", "escalate"}


def normalized(rules: list[dict]) -> dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]]:
    result = {}
    for rule in rules:
        groups = tuple(rule.get("apiGroups", []))
        resources = tuple(rule.get("resources", []))
        verbs = set(rule.get("verbs", []))
        assert groups and resources and verbs
        assert "*" not in groups and "*" not in resources and "*" not in verbs
        assert not FORBIDDEN_RESOURCES.intersection(resources)
        assert not FORBIDDEN_VERBS.intersection(verbs)
        assert "resourceNames" not in rule and "nonResourceURLs" not in rule
        key = (groups, resources)
        assert key not in result
        result[key] = verbs
    return result


def validate(values: dict) -> None:
    assert values["configs"]["cm"]["resource.respectRBAC"] == "normal"
    controller_rules = values["controller"]["clusterRoleRules"]
    assert controller_rules["enabled"] is True
    assert normalized(controller_rules["rules"]) == EXPECTED


def rejected(values: dict) -> None:
    try:
        validate(values)
    except (AssertionError, KeyError, TypeError):
        return
    raise AssertionError("incomplete or broadened controller cache RBAC was accepted")


def main() -> None:
    values = yaml.safe_load((ROOT / "platform/addons/argocd/values.yaml").read_text(encoding="utf-8"))
    validate(values)
    for mode in (None, "", "strict"):
        changed = copy.deepcopy(values)
        if mode is None:
            changed["configs"]["cm"].pop("resource.respectRBAC")
        else:
            changed["configs"]["cm"]["resource.respectRBAC"] = mode
        rejected(changed)
    wildcard = copy.deepcopy(values)
    wildcard["controller"]["clusterRoleRules"]["rules"][5]["resources"] = ["*"]
    rejected(wildcard)
    write_support = copy.deepcopy(values)
    write_support["controller"]["clusterRoleRules"]["rules"][5]["verbs"].append("create")
    rejected(write_support)
    secret = copy.deepcopy(values)
    secret["controller"]["clusterRoleRules"]["rules"].append(
        {"apiGroups": [""], "resources": ["secrets"], "verbs": ["get", "list", "watch"]}
    )
    rejected(secret)
    webhook = copy.deepcopy(values)
    webhook["controller"]["clusterRoleRules"]["rules"].append(
        {"apiGroups": ["admissionregistration.k8s.io"],
         "resources": ["validatingwebhookconfigurations"], "verbs": ["get", "list", "watch"]}
    )
    rejected(webhook)
    impersonation = copy.deepcopy(values)
    impersonation["controller"]["clusterRoleRules"]["rules"][5]["verbs"].append("impersonate")
    rejected(impersonation)
    missing = copy.deepcopy(values)
    missing["controller"]["clusterRoleRules"]["rules"].pop()
    rejected(missing)
    print("PASS  Argo cache respects denied APIs and controller RBAC matches the complete bounded resource contract.")


if __name__ == "__main__":
    main()
