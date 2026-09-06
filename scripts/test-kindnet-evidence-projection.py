#!/usr/bin/env python3
"""Offline regression tests for kindnet's credential-safe evidence projection."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECTOR = ROOT / "scripts/project-kindnet-evidence.py"
SCANNER = ROOT / "scripts/redact-network-diagnostics.py"


def fixture() -> dict:
    return {
        "apiVersion": "apps/v1", "kind": "DaemonSet",
        "metadata": {"name": "kindnet", "namespace": "kube-system", "uid": "daemonset-uid", "generation": 7},
        "spec": {"selector": {"matchLabels": {"app": "kindnet"}}, "template": {
            "metadata": {"labels": {"app": "kindnet", "k8s-app": "kindnet"}},
            "spec": {"containers": [{
                "name": "kindnet-cni", "image": "docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88",
                "env": [
                    {"name": "HOST_IP", "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "status.hostIP"}}},
                    {"name": "POD_IP", "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "status.podIP"}}},
                    {"name": "POD_SUBNET", "value": "10.244.0.0/16"},
                    {"name": "CONTROL_PLANE_ENDPOINT", "value": "platform-engineering-lab-control-plane:6443"},
                ],
            }]},
        }},
        "status": {"desiredNumberScheduled": 3, "currentNumberScheduled": 3, "numberReady": 3},
    }


def pod_fixture(name: str = "kindnet-fixture") -> dict:
    environment = copy.deepcopy(fixture()["spec"]["template"]["spec"]["containers"][0]["env"])
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {
            "name": name, "namespace": "kube-system", "uid": f"uid-{name}",
            "creationTimestamp": "2026-09-05T12:00:00Z",
            "labels": {"app": "kindnet", "k8s-app": "kindnet", "tier": "node", "controller-revision-hash": "hash", "pod-template-generation": "1"},
            "ownerReferences": [{"apiVersion": "apps/v1", "kind": "DaemonSet", "name": "kindnet", "uid": "daemonset-uid", "controller": True, "blockOwnerDeletion": True}],
        },
        "spec": {
            "nodeName": "platform-engineering-lab-worker", "containers": [{"name": "kindnet-cni", "image": fixture()["spec"]["template"]["spec"]["containers"][0]["image"], "env": environment}],
            "volumes": [
                {"name": name, "hostPath": {"path": "/safe"}} for name in ("cni-cfg", "xtables-lock", "lib-modules", "nri-plugin")
            ] + [{"name": "kube-api-access-abc12", "projected": {"sources": [{"serviceAccountToken": {"path": "token"}}, {"configMap": {"name": "kube-root-ca.crt"}}, {"downwardAPI": {"items": []}}]}}],
        },
        "status": {
            "phase": "Running", "startTime": "2026-09-05T12:00:01Z", "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "kindnet-cni", "image": fixture()["spec"]["template"]["spec"]["containers"][0]["image"], "imageID": "sha256:" + "1" * 64, "ready": True, "restartCount": 0, "state": {"running": {"startedAt": "2026-09-05T12:00:01Z"}}}],
        },
    }


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(source: pathlib.Path, output: pathlib.Path, ok: bool) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["python3", str(PROJECTOR), "--source", str(source), "--output", str(output)], text=True, capture_output=True)
    assert (result.returncode == 0) is ok, (result.stdout, result.stderr)
    return result


def changed(value: dict, operation) -> dict:
    result = copy.deepcopy(value)
    operation(result["spec"]["template"]["spec"]["containers"][0])
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="kindnet evidence projection ") as directory:
        root = pathlib.Path(directory); source = root / "source.json"; output = root / "projected.json"
        source.write_text(json.dumps(fixture()), encoding="utf-8")
        invoke(source, output, True)
        projection = json.loads(output.read_text(encoding="utf-8"))
        assert projection["daemonSet"]["downwardAPIFields"] == [
            {"name": "HOST_IP", "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "status.hostIP"}}},
            {"name": "POD_IP", "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "status.podIP"}}},
        ]
        serialized = output.read_text(encoding="utf-8")
        assert '"env"' not in serialized and '"envFrom"' not in serialized and '"value"' not in serialized
        assert "10.244." not in serialized and ":6443" not in serialized
        subprocess.run(["python3", str(SCANNER), str(output)], check=True, capture_output=True)
        assert output.stat().st_mode & 0o777 == 0o600

        for workload in (pod_fixture(), {"apiVersion": "v1", "kind": "PodList", "items": [pod_fixture("kindnet-a"), pod_fixture("kindnet-b")]}):
            source.write_text(json.dumps(workload), encoding="utf-8")
            invoke(source, output, True)
            projected_text = output.read_text(encoding="utf-8")
            assert json.loads(projected_text)["projectionType"] in {"kindnet-pod", "kindnet-pod-list"}
            assert all(item not in projected_text for item in ('"env"', '"envFrom"', '"volumes"', '"serviceAccountToken"', '"value"'))
            subprocess.run(["python3", str(SCANNER), str(output)], check=True, capture_output=True)
        source.write_text(json.dumps(pod_fixture()), encoding="utf-8"); invoke(source, output, True)
        projected_pod = json.loads(output.read_text())["pod"]
        assert projected_pod["nodeName"] == "platform-engineering-lab-worker"
        assert projected_pod["metadata"]["name"] == "kindnet-fixture" and projected_pod["metadata"]["uid"] == "uid-kindnet-fixture"
        assert projected_pod["container"]["ready"] is True and projected_pod["container"]["restartCount"] == 0

        cases = [
            changed(fixture(), lambda c: c["env"].pop()),
            changed(fixture(), lambda c: c["env"].append({"name": "EXTRA", "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "metadata.name"}}})),
            changed(fixture(), lambda c: c["env"].append(copy.deepcopy(c["env"][0]))),
            changed(fixture(), lambda c: c["env"][0]["valueFrom"]["fieldRef"].update(fieldPath="metadata.name")),
            changed(fixture(), lambda c: c["env"].__setitem__(0, {"name": "HOST_IP", "value": "literal"})),
            changed(fixture(), lambda c: c["env"].__setitem__(0, {"name": "HOST_IP", "valueFrom": {"secretKeyRef": {"name": "x", "key": "x"}}})),
            changed(fixture(), lambda c: c["env"].__setitem__(0, {"name": "HOST_IP", "valueFrom": {"configMapKeyRef": {"name": "x", "key": "x"}}})),
            changed(fixture(), lambda c: c.update(envFrom=[{"secretRef": {"name": "x"}}])),
            changed(fixture(), lambda c: c["env"].__setitem__(0, {"name": "HOST_IP", "valueFrom": {"resourceFieldRef": {"resource": "limits.cpu"}}})),
            changed(fixture(), lambda c: c["env"][0].update(authorization="Bearer nested-credential")),
            changed(fixture(), lambda c: c["env"][2].update(value="unexpected")),
        ]
        for index, value in enumerate(cases):
            bad_source, bad_output = root / f"bad-{index}.json", root / f"bad-{index}-output.json"
            bad_source.write_text(json.dumps(value), encoding="utf-8")
            invoke(bad_source, bad_output, False)
            assert not bad_output.exists()

        pod_cases = []
        for field in ("initContainers", "ephemeralContainers"):
            value = pod_fixture(); value["spec"][field] = [{"name": "unexpected"}]; pod_cases.append(value)
        value = pod_fixture(); value["spec"]["volumes"].append({"name": "secret", "secret": {"secretName": "x"}}); pod_cases.append(value)
        value = pod_fixture(); value["spec"]["volumes"][-1]["projected"]["sources"].append({"secret": {"name": "x"}}); pod_cases.append(value)
        value = pod_fixture(); value["spec"]["containers"].append(copy.deepcopy(value["spec"]["containers"][0])); pod_cases.append(value)
        value = pod_fixture(); value["spec"]["containers"][0]["image"] = "unexpected:latest"; pod_cases.append(value)
        for index, value in enumerate(pod_cases):
            bad_source, bad_output = root / f"bad-pod-{index}.json", root / f"bad-pod-{index}-output.json"
            bad_source.write_text(json.dumps(value), encoding="utf-8"); invoke(bad_source, bad_output, False)
            assert not bad_output.exists()
        wrong_schema = pod_fixture(); wrong_schema["apiVersion"] = "v2"
        source.write_text(json.dumps(wrong_schema), encoding="utf-8"); invoke(source, output, False)

        sentinel = root / "incomplete-evidence.json"
        sentinel.write_text('{"incomplete":true}\n', encoding="utf-8"); before = digest(sentinel)
        source.write_text(json.dumps(cases[0]), encoding="utf-8")
        invoke(source, sentinel, False)
        assert digest(sentinel) == before and not list(root.glob(".*.tmp"))

        source.write_text(json.dumps(fixture()), encoding="utf-8")
        shell_output = root / "POSIX output with spaces.json"
        entry = subprocess.run(
            ["/bin/sh", "-c", 'python3 "$1" --source "$2" --output "$3" && python3 "$4" "$3"',
             "entry", str(PROJECTOR), str(source), str(shell_output), str(SCANNER)],
            text=True, capture_output=True,
        )
        assert entry.returncode == 0, (entry.stdout, entry.stderr)
    print("PASS  kindnet evidence retains only exact downward-API references and excludes literal environment values.")
    print("PASS  unsafe references, malformed entries, credentials, and non-atomic evidence updates are rejected.")


if __name__ == "__main__":
    main()
