#!/usr/bin/env python3
"""Validate Phase 4 rendered and declarative security contracts."""

from __future__ import annotations

import argparse
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_REPOSITORY = "https://github.com/Rano1000/platform-engineering-lab.git"
ARGO_IMAGE = "quay.io/argoproj/argocd:v3.5.2@sha256:e2aadfae709d904e87f46ba4aa49601d827b3022db22cd4d03aae816a2e7097b"
REDIS_IMAGE = "docker.io/library/redis:8.6.4-alpine@sha256:2cc044fc5a07c9b701f8f1255a309ae9ad7856e694ac03513bf3648c01e40763"
DIGEST_REFERENCE = re.compile(r"^[^@]+@sha256:[0-9a-f]{64}$")


def documents(path: pathlib.Path) -> list[dict]:
    return [item for item in yaml.safe_load_all(path.read_text(encoding="utf-8")) if isinstance(item, dict)]


def validate_application_renders(local: pathlib.Path, gitops: pathlib.Path) -> None:
    local_deployment = next(item for item in documents(local) if item.get("kind") == "Deployment")
    gitops_deployment = next(item for item in documents(gitops) if item.get("kind") == "Deployment")
    local_image = local_deployment["spec"]["template"]["spec"]["containers"][0]["image"]
    gitops_image = gitops_deployment["spec"]["template"]["spec"]["containers"][0]["image"]
    assert local_image == "golden-path-api:0.1.0-0123456789ab"
    assert gitops_image == "ghcr.io/rano1000/golden-path-api@sha256:" + "a" * 64
    assert local_deployment["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] == "Never"
    assert gitops_deployment["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] == "IfNotPresent"


def pod_spec(resource: dict) -> dict | None:
    kind = resource.get("kind")
    spec = resource.get("spec", {})
    if kind == "Pod":
        return spec
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        return spec.get("template", {}).get("spec", {})
    return None


def validate_argocd(path: pathlib.Path) -> None:
    rendered = documents(path)
    workloads = [(item, pod_spec(item)) for item in rendered if pod_spec(item) is not None]
    assert workloads, "no Argo workloads rendered"
    images: set[str] = set()
    for resource, spec in workloads:
        assert spec.get("hostNetwork") is not True
        pod_security = spec.get("securityContext", {})
        assert pod_security.get("runAsNonRoot") is True
        assert pod_security.get("seccompProfile", {}).get("type") == "RuntimeDefault"
        for container in (spec.get("initContainers") or []) + (spec.get("containers") or []):
            image = container.get("image", "")
            images.add(image)
            assert DIGEST_REFERENCE.fullmatch(image), f"mutable image in {resource['metadata']['name']}: {image}"
            security = container.get("securityContext", {})
            assert security.get("allowPrivilegeEscalation") is False
            assert security.get("privileged") is not True
            assert security.get("capabilities", {}).get("drop") == ["ALL"]
            resources = container.get("resources", {})
            assert resources.get("requests") and resources.get("limits"), f"missing resources for {container['name']}"
            for port in container.get("ports") or []:
                assert not port.get("hostPort")
    assert images == {ARGO_IMAGE, REDIS_IMAGE}, images
    for service in (item for item in rendered if item.get("kind") == "Service"):
        assert service.get("spec", {}).get("type", "ClusterIP") == "ClusterIP"
    forbidden_kinds = {"Ingress", "HTTPRoute", "HorizontalPodAutoscaler", "PersistentVolumeClaim"}
    assert not [(item.get("kind"), item.get("metadata", {}).get("name")) for item in rendered if item.get("kind") in forbidden_kinds]
    cluster_bindings = [item for item in rendered if item.get("kind") == "ClusterRoleBinding"]
    assert all(item.get("roleRef", {}).get("name") != "cluster-admin" for item in cluster_bindings)
    for role in (item for item in rendered if item.get("kind") == "ClusterRole"):
        for rule in role.get("rules", []):
            assert "*" not in rule.get("apiGroups", []), f"wildcard API group in {role['metadata']['name']}"
            assert "*" not in rule.get("resources", []), f"wildcard resource in {role['metadata']['name']}"
            assert "*" not in rule.get("verbs", []), f"wildcard verb in {role['metadata']['name']}"


def validate_projects_and_root() -> None:
    project = yaml.safe_load((ROOT / "environments/local/gitops/workload-project.yaml").read_text(encoding="utf-8"))
    spec = project["spec"]
    assert spec["sourceRepos"] == [APP_REPOSITORY]
    assert spec["destinations"] == [{"server": "https://kubernetes.default.svc", "namespace": "platform-apps"}]
    allowed = {(item["group"], item["kind"]) for item in spec["namespaceResourceWhitelist"]}
    expected = {
        ("", "ConfigMap"), ("", "Service"), ("", "ServiceAccount"),
        ("apps", "Deployment"), ("policy", "PodDisruptionBudget"),
        ("networking.k8s.io", "NetworkPolicy"), ("gateway.networking.k8s.io", "HTTPRoute"),
    }
    assert allowed == expected
    assert not any("*" in item for item in allowed)
    assert spec["clusterResourceBlacklist"] == [{"group": "*", "kind": "*"}]
    bootstrap = yaml.safe_load((ROOT / "environments/local/gitops/bootstrap-project.yaml").read_text(encoding="utf-8"))
    bootstrap_spec = bootstrap["spec"]
    assert bootstrap_spec["sourceRepos"] == [APP_REPOSITORY]
    assert bootstrap_spec["destinations"] == [{"server": "https://kubernetes.default.svc", "namespace": "gitops"}]
    assert bootstrap_spec["namespaceResourceWhitelist"] == [{"group": "argoproj.io", "kind": "Application"}]
    assert bootstrap_spec["clusterResourceBlacklist"] == [{"group": "*", "kind": "*"}]
    root = yaml.safe_load((ROOT / "environments/local/gitops/root-application.yaml").read_text(encoding="utf-8"))
    assert root["metadata"]["name"] == "platform-environment"
    assert "finalizers" not in root["metadata"]
    assert root["spec"]["project"] == "platform-bootstrap"
    assert root["spec"]["source"] == {
        "repoURL": APP_REPOSITORY,
        "targetRevision": "main",
        "path": "environments/local/gitops/applications",
        "directory": {"include": "*.yaml", "recurse": False},
    }
    assert root["spec"]["destination"] == {"server": "https://kubernetes.default.svc", "namespace": "gitops"}
    assert "automated" not in root["spec"].get("syncPolicy", {})
    application_directory = ROOT / "environments/local/gitops/applications"
    for manifest in application_directory.glob("*.yaml"):
        child = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        assert child.get("kind") == "Application" and child.get("apiVersion") == "argoproj.io/v1alpha1"


def validate_network_policies() -> None:
    policies = documents(ROOT / "platform/addons/argocd/network-policies.yaml")
    assert len(policies) == 5
    text = (ROOT / "platform/addons/argocd/network-policies.yaml").read_text(encoding="utf-8")
    assert "platform-apps" not in text
    assert "port: 443" in text and "port: 6379" in text and "port: 8081" in text
    assert "0.0.0.0/0" in text


def validate_workflow() -> None:
    path = ROOT / ".github/workflows/application-ci.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert "pull_request_target" not in text
    assert text.count("packages: write") == 1
    assert "GHCR_PUBLICATION_APPROVED" in text
    assert "./scripts/detect-image-impact.py" in text
    assert "./scripts/verify-promotion-artifacts.sh artifacts" in text
    assert "./scripts/verify-promotion-artifacts.sh image" in text
    assert "./scripts/supply-chain.sh scan-reference" in text
    assert "contents: write" in text and "pull-requests: write" in text
    assert "chart-promotion:" in text
    assert "chart_changed" in text
    assert workflow["permissions"] == {"contents": "read"}
    action_pattern = re.compile(r"uses:\s+[^\s@]+@([0-9a-f]{40})(?:\s|$)")
    uses = [line for line in text.splitlines() if "uses:" in line]
    assert all(action_pattern.search(line) for line in uses), uses
    chart_script = (ROOT / "scripts/create-chart-promotion-pr.sh").read_text(encoding="utf-8")
    assert "helm template" in chart_script and "image_digest" in chart_script
    assert "--force" not in chart_script and "--force" not in (ROOT / "scripts/create-promotion-pr.sh").read_text(encoding="utf-8")
    assert "environments/local/gitops/applications/golden-path-api.yaml" in chart_script
    assert "environments/local/gitops/evidence/golden-path-api.json" in chart_script


def validate_ownership_guards() -> None:
    app = (ROOT / "scripts/app.sh").read_text(encoding="utf-8")
    deploy = app[app.index("deploy_app()") : app.index("status_app()")]
    uninstall = app[app.index("uninstall_app()") : app.index("network_test()")]
    assert "refuse_helm_mutation_when_gitops_owned" in deploy
    assert "refuse_helm_mutation_when_gitops_owned" in uninstall
    common = (ROOT / "scripts/lib/app-common.sh").read_text(encoding="utf-8")
    assert "argo_application_owns_workload" in common
    assert "argocd\\.argoproj\\.io/tracking-id" in common
    guard = common[common.index("refuse_helm_mutation_when_gitops_owned()") :]
    assert "argo_application_owns_workload" in guard and "argo_application_exists" not in guard
    template = (ROOT / "environments/local/gitops/applications/golden-path-api.yaml.tmpl").read_text(encoding="utf-8")
    assert 'targetRevision: "${CHART_REVISION}"' in template
    assert 'revision: "${IMAGE_SOURCE_REVISION}"' in template
    assert "automated:" not in template and "prune:" not in template and "selfHeal:" not in template
    assert "finalizers:" not in template
    gitops = (ROOT / "scripts/gitops.sh").read_text(encoding="utf-8")
    for operation in ("root_sync", "app_sync"):
        assert operation in gitops
    assert "require_clean_synchronized_repository" in gitops
    root_sync = gitops[gitops.index("root_sync()") : gitops.index("app_status()")]
    root_diff = gitops[gitops.index("root_diff()") : gitops.index("root_sync()")]
    app_sync = gitops[gitops.index("app_sync()") : gitops.index("uninstall_gitops()")]
    assert 'argocd app diff "$ARGOCD_ROOT_APPLICATION" --core --revision "$environment_revision"' in root_sync
    assert 'argocd app sync "$ARGOCD_ROOT_APPLICATION" --core --revision "$environment_revision" --prune=false' in root_sync
    assert "child_spec_checksum" in root_sync and "require_environment_revision_current" in root_sync
    assert root_sync.count("require_environment_revision_current") == 2
    assert "/sha256:$child_spec_checksum" in root_sync
    assert "--revision main" not in root_sync
    assert 'argocd app diff "$ARGOCD_ROOT_APPLICATION" --core --revision "$environment_revision"' in root_diff
    assert "child_spec_checksum" in root_diff
    assert f'argocd app sync "$ARGOCD_APPLICATION" --core --revision "$chart_revision" --prune=false' in app_sync
    assert root_sync.index("argocd app diff") < root_sync.index("confirm_exact") < root_sync.index("argocd app sync")
    assert app_sync.index("argocd app diff") < app_sync.index("confirm_exact") < app_sync.index("argocd app sync")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-render", required=True, type=pathlib.Path)
    parser.add_argument("--gitops-render", required=True, type=pathlib.Path)
    parser.add_argument("--argocd-render", required=True, type=pathlib.Path)
    args = parser.parse_args()
    validate_application_renders(args.local_render, args.gitops_render)
    validate_argocd(args.argocd_render)
    validate_projects_and_root()
    validate_network_policies()
    validate_workflow()
    validate_ownership_guards()
    print("PASS  Phase 4 image, Argo CD, RBAC, project, network, and workflow contracts are valid.")


if __name__ == "__main__":
    main()
