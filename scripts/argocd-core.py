#!/usr/bin/env python3
"""Run the pinned Argo CD CLI in core mode with an isolated namespace binding."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile

EXPECTED_CONTEXT = "kind-platform-engineering-lab"
ARGOCD_NAMESPACE = "gitops"
ARGOCD_VERSION = "v3.5.2"
SAFE_PATH = "/usr/bin:/bin"


class CoreBindingError(RuntimeError):
    pass


def require_identity() -> None:
    if EXPECTED_CONTEXT != "kind-platform-engineering-lab":
        raise CoreBindingError("Argo CD core context identity was altered")
    if ARGOCD_NAMESPACE != "gitops":
        raise CoreBindingError("Argo CD core namespace identity was altered")


def validate_cli(cli: pathlib.Path) -> None:
    if not cli.is_absolute() or not cli.is_file():
        raise CoreBindingError("Argo CD CLI must be an absolute regular-file path")
    result = subprocess.run(
        [str(cli), "version", "--client", "--short"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
    )
    match = re.search(r"\b(v\d+\.\d+\.\d+)(?:\+[^\s]+)?\b", result.stdout)
    if result.returncode != 0 or not match or match.group(1) != ARGOCD_VERSION:
        raise CoreBindingError(f"Argo CD CLI must report exactly {ARGOCD_VERSION}")


def validate_kubeconfig_document(document: dict) -> None:
    contexts = document.get("contexts")
    clusters = document.get("clusters")
    users = document.get("users")
    current = document.get("current-context")
    if current != EXPECTED_CONTEXT or not all(isinstance(value, list) and len(value) == 1 for value in (contexts, clusters, users)):
        raise CoreBindingError("isolated kubeconfig must contain only the exact lab context")
    entry = contexts[0]
    if entry.get("name") != EXPECTED_CONTEXT or entry.get("context", {}).get("namespace") != ARGOCD_NAMESPACE:
        raise CoreBindingError("isolated kubeconfig namespace is not exactly gitops")
    cluster_name = entry.get("context", {}).get("cluster")
    user_name = entry.get("context", {}).get("user")
    if clusters[0].get("name") != cluster_name or users[0].get("name") != user_name:
        raise CoreBindingError("isolated kubeconfig has an incomplete context identity")
    cluster = clusters[0].get("cluster", {})
    user = users[0].get("user", {})
    if not re.fullmatch(r"https://127\.0\.0\.1:\d+", cluster.get("server", "")) or not cluster.get("certificate-authority-data"):
        raise CoreBindingError("isolated kubeconfig does not identify the local kind API")
    if set(user) != {"client-certificate-data", "client-key-data"} or not all(user.values()):
        raise CoreBindingError("isolated kubeconfig credentials are not the expected kind client certificate pair")


def restrictive_file(path: pathlib.Path, content: bytes = b""):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stream = os.fdopen(descriptor, "wb")
    if content:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return stream


def prepare_isolated_kubeconfig(kubectl: str, directory: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    source_context = subprocess.run(
        [kubectl, "config", "current-context"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    if source_context != EXPECTED_CONTEXT:
        raise CoreBindingError(f"active Kubernetes context must be {EXPECTED_CONTEXT}; found {source_context or 'empty'}")
    kubeconfig = directory / "core-kubeconfig"
    with restrictive_file(kubeconfig) as stream:
        subprocess.run(
            [kubectl, "--context", EXPECTED_CONTEXT, "config", "view", "--raw", "--minify", "-o", "json"],
            check=True,
            stdout=stream,
            stderr=subprocess.PIPE,
        )
    subprocess.run(
        [kubectl, "--kubeconfig", str(kubeconfig), "config", "set-context", EXPECTED_CONTEXT, f"--namespace={ARGOCD_NAMESPACE}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    document = json.loads(
        subprocess.run(
            [kubectl, "--kubeconfig", str(kubeconfig), "config", "view", "--raw", "--minify", "-o", "json"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    )
    validate_kubeconfig_document(document)
    if stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
        raise CoreBindingError("isolated kubeconfig permissions must be 0600")
    client_config = directory / "argocd-config"
    with restrictive_file(client_config, b"{}\n") as stream:
        stream.close()
    return kubeconfig, client_config


def sanitized_environment(home: pathlib.Path, kubeconfig: pathlib.Path) -> dict[str, str]:
    return {"HOME": str(home), "KUBECONFIG": str(kubeconfig), "PATH": SAFE_PATH}


def core_command(cli: pathlib.Path, kubeconfig: pathlib.Path, client_config: pathlib.Path, arguments: list[str]) -> list[str]:
    if not arguments or arguments[0] != "app" or arguments[1:2] not in (["diff"], ["sync"]):
        raise CoreBindingError("only guarded Argo CD app diff and sync operations are supported")
    return [
        str(cli),
        *arguments,
        "--core",
        "--kube-context",
        EXPECTED_CONTEXT,
        "--config",
        str(client_config),
        "--app-namespace",
        ARGOCD_NAMESPACE,
    ]


def run(cli: pathlib.Path, arguments: list[str]) -> int:
    require_identity()
    validate_cli(cli)
    kubectl = shutil.which("kubectl")
    if not kubectl:
        raise CoreBindingError("kubectl is required to prepare the isolated core-mode context")
    with tempfile.TemporaryDirectory(prefix="platform-engineering-lab-argocd-core-") as value:
        directory = pathlib.Path(value)
        directory.chmod(0o700)
        home = directory / "home"
        home.mkdir(mode=0o700)
        kubeconfig, client_config = prepare_isolated_kubeconfig(kubectl, directory)
        command = core_command(cli, kubeconfig, client_config, arguments)
        return subprocess.run(command, check=False, env=sanitized_environment(home, kubeconfig)).returncode


def expect_failure(action, label: str) -> None:
    try:
        action()
    except CoreBindingError:
        return
    raise AssertionError(f"{label} was accepted")


def self_test() -> None:
    require_identity()
    valid = {
        "current-context": EXPECTED_CONTEXT,
        "contexts": [{"name": EXPECTED_CONTEXT, "context": {"cluster": "lab", "user": "lab", "namespace": "gitops"}}],
        "clusters": [{"name": "lab", "cluster": {"server": "https://127.0.0.1:12345", "certificate-authority-data": "fixture"}}],
        "users": [{"name": "lab", "user": {"client-certificate-data": "fixture", "client-key-data": "fixture"}}],
    }
    validate_kubeconfig_document(valid)
    for namespace in ("", "argocd", "external"):
        changed = json.loads(json.dumps(valid))
        changed["contexts"][0]["context"]["namespace"] = namespace
        expect_failure(lambda value=changed: validate_kubeconfig_document(value), f"namespace {namespace!r}")
    changed_context = json.loads(json.dumps(valid))
    changed_context["current-context"] = "other"
    expect_failure(lambda: validate_kubeconfig_document(changed_context), "altered context")
    path = pathlib.Path("/tmp/path with spaces/argocd")
    kubeconfig = pathlib.Path("/tmp/path with spaces/core kubeconfig")
    config = pathlib.Path("/tmp/path with spaces/argocd config")
    for operation in (["app", "diff", "root"], ["app", "sync", "root"], ["app", "diff", "child"], ["app", "sync", "child"]):
        command = core_command(path, kubeconfig, config, operation)
        assert command[0] == str(path)
        assert command[-2:] == ["--app-namespace", "gitops"]
        assert ["--kube-context", EXPECTED_CONTEXT] == command[command.index("--kube-context") : command.index("--kube-context") + 2]
        assert command[command.index("--config") + 1] == str(config)
    environment = sanitized_environment(pathlib.Path("/tmp/home"), kubeconfig)
    assert environment == {"HOME": "/tmp/home", "KUBECONFIG": str(kubeconfig), "PATH": SAFE_PATH}
    assert "ARGOCD_NAMESPACE" not in environment and "ARGOCD_SERVER" not in environment
    print("PASS  all guarded Argo core commands use the isolated gitops namespace and ignore external overrides.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cli", type=pathlib.Path)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        if args.cli is None or not args.arguments or args.arguments[0] != "--":
            raise CoreBindingError("usage: argocd-core.py --cli ABSOLUTE_PATH -- app {diff|sync} ...")
        return run(args.cli, args.arguments[1:])
    except (CoreBindingError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
