#!/usr/bin/env python3
"""Verify metrics validation policy ownership stays outside the workload chart."""

from __future__ import annotations

import copy
import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_NAMESPACE = "platform-apps"
TEMPORARY_POLICY = "metrics-test-egress-$suffix"
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
    metrics_rule = policies[0]["spec"]["ingress"][1]
    assert metrics_rule["ports"] == [{"protocol": "TCP", "port": 8080}]
    assert metrics_rule["from"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "observability"
    }
    assert metrics_rule["from"][0]["podSelector"]["matchLabels"] == {
        "platform.engineering-lab/purpose": "metrics-test"
    }


def validate_harness(content: str) -> None:
    required = (
        f'policy="{TEMPORARY_POLICY}"',
        'kubectl_lab delete networkpolicy "$policy" --namespace observability',
        'kubectl_lab get "$app_cleanup_resource" --namespace observability',
        "app.kubernetes.io/managed-by: platform-engineering-lab",
        "platform.engineering-lab/purpose: metrics-test",
        "platform.engineering-lab/run-id: $suffix",
        "kind: NetworkPolicy",
        "namespace: observability",
        "port: 8080",
    )
    assert all(value in content for value in required)
    assert OLD_POLICY not in content
    assert content.index('trap cleanup_on_exit') < content.index('kubectl_lab apply -f -')


def rejected(action, label: str) -> None:
    try:
        action()
    except AssertionError:
        return
    raise AssertionError(f"{label} was accepted")


def main() -> None:
    documents = render_chart()
    validate_documents(documents)
    harness = (ROOT / "scripts/app.sh").read_text(encoding="utf-8")
    validate_harness(harness)
    cross_namespace = copy.deepcopy(documents)
    cross_namespace[0].setdefault("metadata", {})["namespace"] = "observability"
    rejected(lambda: validate_documents(cross_namespace), "cross-namespace chart output")
    rejected(lambda: validate_harness(harness.replace("kind: NetworkPolicy", "kind: ConfigMap")), "lost metrics isolation policy")
    rejected(lambda: validate_harness(harness.replace(TEMPORARY_POLICY, OLD_POLICY)), "ambiguous permanent policy ownership")
    print("PASS  metrics isolation uses a uniquely owned temporary observability policy; the chart stays in platform-apps.")


if __name__ == "__main__":
    main()
