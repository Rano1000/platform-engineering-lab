#!/usr/bin/env python3
"""Verify metrics validation policy ownership stays outside the workload chart."""

from __future__ import annotations

import copy
import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_NAMESPACE = "platform-apps"
TEMPORARY_POLICY = "metrics-test-egress-$ant_suffix"
OLD_POLICY = "golden-path-golden-path-api-metrics-test-egress"


def render_chart() -> list[dict]:
    output = subprocess.run(
        [
            "helm", "template", "golden-path", str(ROOT / "charts/golden-path-api"),
            "--namespace", APP_NAMESPACE, "--kube-version", "1.35.0",
            "--set-string", "image.tag=",
            "--set-string", "image.repository=ghcr.io/rano1000/golden-path-api",
            "--set-string", "image.digest=sha256:" + "a" * 64,
            "--set-string", "image.revision=" + "b" * 40,
            "--set-string", "image.pullPolicy=IfNotPresent",
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    return [item for item in yaml.safe_load_all(output) if isinstance(item, dict)]


def validate_documents(documents: list[dict]) -> None:
    for document in documents:
        namespace = document.get("metadata", {}).get("namespace", APP_NAMESPACE)
        assert namespace == APP_NAMESPACE, (document.get("kind"), namespace)
    policies = [item for item in documents if item.get("kind") == "NetworkPolicy"]
    assert len(policies) == 1
    assert policies[0]["metadata"]["name"] == "golden-path-golden-path-api-allow-approved-ingress"
    assert OLD_POLICY not in {item["metadata"]["name"] for item in documents}
    assert len(policies[0]["spec"]["ingress"]) == 1
    assert policies[0]["spec"]["ingress"][0]["from"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "platform-system"
    }


def validate_harness(content: str) -> None:
    required = (
        f'ant_policy="{TEMPORARY_POLICY}"',
        'ant_ingress_policy="metrics-test-ingress-$ant_suffix"',
        'cleanup-kubernetes-resource.py" cleanup',
        '--namespace "$ANT_NAMESPACE"',
        "app.kubernetes.io/managed-by: platform-engineering-lab",
        "platform.engineering-lab/purpose: metrics-test",
        "platform.engineering-lab/run-id: $ant_suffix",
        "kind: NetworkPolicy",
        "ANT_NAMESPACE=observability",
        "port: 8080",
    )
    assert all(value in content for value in required)
    assert OLD_POLICY not in content
    assert "--ignore-not-found" not in content
    assert content.index("ant_capture_context") < content.index("ant_cleanup_resource networkpolicy")


def rejected(action, label: str) -> None:
    try:
        action()
    except AssertionError:
        return
    raise AssertionError(f"{label} was accepted")


def main() -> None:
    documents = render_chart()
    validate_documents(documents)
    harness = (ROOT / "scripts/test-app-network.sh").read_text(encoding="utf-8")
    validate_harness(harness)
    cross_namespace = copy.deepcopy(documents)
    cross_namespace[0].setdefault("metadata", {})["namespace"] = "observability"
    rejected(lambda: validate_documents(cross_namespace), "cross-namespace chart output")
    rejected(lambda: validate_harness(harness.replace("kind: NetworkPolicy", "kind: ConfigMap")), "lost metrics isolation policy")
    rejected(lambda: validate_harness(harness.replace(TEMPORARY_POLICY, OLD_POLICY)), "ambiguous permanent policy ownership")
    print("PASS  metrics isolation uses exact temporary ingress and egress policies; permanent ingress trusts only Traefik.")


if __name__ == "__main__":
    main()
