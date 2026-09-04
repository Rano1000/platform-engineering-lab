#!/usr/bin/env python3
"""Offline regression coverage for guarded kindnet recovery and enforcement."""

import copy
import json
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-kindnet-recovery.py"
ENFORCEMENT = ROOT / "scripts/validate-kindnet-enforcement.py"
IMAGE = "docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88"
IMAGE_ID = "sha256:" + "1" * 64
NODES = (
    "platform-engineering-lab-control-plane",
    "platform-engineering-lab-worker",
    "platform-engineering-lab-worker2",
)


def fixture():
    daemonset = {
        "metadata": {"name": "kindnet", "namespace": "kube-system", "uid": "ds-uid", "generation": 7},
        "spec": {
            "selector": {"matchLabels": {"app": "kindnet"}},
            "template": {
                "metadata": {"labels": {"app": "kindnet", "k8s-app": "kindnet", "tier": "node"}},
                "spec": {"containers": [{"image": IMAGE}]},
            },
        },
        "status": {"desiredNumberScheduled": 3, "currentNumberScheduled": 3, "numberReady": 3},
    }
    items = []
    for index, node in enumerate(reversed(NODES)):
        items.append({
            "metadata": {
                "name": f"kindnet-{index}", "uid": f"uid-{node}",
                "labels": {"app": "kindnet", "k8s-app": "kindnet", "tier": "node"},
                "ownerReferences": [{
                    "apiVersion": "apps/v1", "kind": "DaemonSet", "name": "kindnet",
                    "uid": "ds-uid", "controller": True,
                }],
            },
            "spec": {"nodeName": node, "containers": [{"image": IMAGE}]},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "image": IMAGE, "imageID": IMAGE_ID, "ready": True, "restartCount": 1,
                }],
            },
        })
    return daemonset, {"items": items}


def run(*args, ok=True):
    value = subprocess.run(["python3", str(VALIDATOR), *args], text=True, capture_output=True)
    assert (value.returncode == 0) == ok, (args, value.stdout, value.stderr)
    return value


def write(root, name, value):
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def rejected_preflight(root, daemonset, pods, name):
    run(
        "preflight", "--daemonset", str(write(root, f"{name}-ds.json", daemonset)),
        "--pods", str(write(root, f"{name}-pods.json", pods)), "--image", IMAGE,
        "--output", str(root / f"{name}-identity.json"), ok=False,
    )


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        daemonset, pods = fixture()
        daemonset_path, pods_path = write(root, "ds.json", daemonset), write(root, "pods.json", pods)
        identity_path = root / "identity.json"
        run(
            "preflight", "--daemonset", str(daemonset_path), "--pods", str(pods_path),
            "--image", IMAGE, "--output", str(identity_path),
        )
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        assert [pod["node"] for pod in identity["pods"]] == list(NODES)
        assert identity["selector"] == {"matchLabels": {"app": "kindnet"}}
        confirmation = run(
            "confirmation", "--identity", str(identity_path), "--context", "kind-platform-engineering-lab",
        ).stdout.strip()
        assert confirmation == (
            "kind-platform-engineering-lab/kindnet/ds-uid/"
            "uid-platform-engineering-lab-control-plane,uid-platform-engineering-lab-worker,"
            "uid-platform-engineering-lab-worker2"
        )
        plan = run("plan", "--identity", str(identity_path)).stdout.splitlines()
        assert [line.split("|")[0] for line in plan] == list(NODES)

        mutations = []
        old_selector = copy.deepcopy(daemonset)
        old_selector["spec"]["selector"] = {"matchLabels": {"k8s-app": "kindnet"}}
        mutations.append(("old-selector", old_selector, pods))
        missing_app = copy.deepcopy(daemonset)
        del missing_app["spec"]["selector"]["matchLabels"]["app"]
        mutations.append(("missing-app", missing_app, pods))
        wrong_value = copy.deepcopy(daemonset)
        wrong_value["spec"]["selector"]["matchLabels"]["app"] = "other"
        mutations.append(("wrong-value", wrong_value, pods))
        additional = copy.deepcopy(daemonset)
        additional["spec"]["selector"]["matchLabels"]["k8s-app"] = "kindnet"
        mutations.append(("additional-selector", additional, pods))
        expression = copy.deepcopy(daemonset)
        expression["spec"]["selector"]["matchExpressions"] = [{"key": "tier", "operator": "Exists"}]
        mutations.append(("match-expression", expression, pods))
        template_mismatch = copy.deepcopy(daemonset)
        del template_mismatch["spec"]["template"]["metadata"]["labels"]["k8s-app"]
        mutations.append(("template-mismatch", template_mismatch, pods))
        wrong_image = copy.deepcopy(daemonset)
        wrong_image["spec"]["template"]["spec"]["containers"][0]["image"] = "latest"
        mutations.append(("wrong-image", wrong_image, pods))
        for name, changed_daemonset, changed_pods in mutations:
            rejected_preflight(root, changed_daemonset, changed_pods, name)

        pod_mutations = []
        missing_node = copy.deepcopy(pods); missing_node["items"].pop()
        pod_mutations.append(("missing-node", missing_node))
        duplicate_node = copy.deepcopy(pods); duplicate_node["items"].append(copy.deepcopy(duplicate_node["items"][0]))
        duplicate_node["items"][-1]["metadata"]["uid"] = "duplicate"
        pod_mutations.append(("duplicate-node", duplicate_node))
        wrong_owner = copy.deepcopy(pods); wrong_owner["items"][0]["metadata"]["ownerReferences"][0]["kind"] = "ReplicaSet"
        pod_mutations.append(("wrong-owner", wrong_owner))
        wrong_uid = copy.deepcopy(pods); wrong_uid["items"][0]["metadata"]["ownerReferences"][0]["uid"] = "other-ds"
        pod_mutations.append(("wrong-daemonset-uid", wrong_uid))
        missing_label = copy.deepcopy(pods); del missing_label["items"][0]["metadata"]["labels"]["app"]
        pod_mutations.append(("pod-selector-mismatch", missing_label))
        wrong_pod_image = copy.deepcopy(pods); wrong_pod_image["items"][0]["spec"]["containers"][0]["image"] = "latest"
        pod_mutations.append(("wrong-pod-image", wrong_pod_image))
        unready = copy.deepcopy(pods); unready["items"][0]["status"]["containerStatuses"][0]["ready"] = False
        pod_mutations.append(("unready", unready))
        bad_runtime = copy.deepcopy(pods); bad_runtime["items"][0]["status"]["containerStatuses"][0]["imageID"] = "short"
        pod_mutations.append(("bad-runtime-image", bad_runtime))
        for name, changed_pods in pod_mutations:
            rejected_preflight(root, daemonset, changed_pods, name)

        changed_generation = copy.deepcopy(daemonset); changed_generation["metadata"]["generation"] = 8
        pod = pods["items"][1]
        run(
            "unchanged", "--identity", str(identity_path),
            "--daemonset", str(write(root, "changed-generation.json", changed_generation)),
            "--pod", str(write(root, "pod.json", pod)), "--node", pod["spec"]["nodeName"],
            "--uid", pod["metadata"]["uid"], ok=False,
        )

        ready_daemonset = copy.deepcopy(daemonset)
        ready_pods = copy.deepcopy(pods)
        write(root, "ready-ds.json", ready_daemonset); write(root, "ready-pods.json", ready_pods)
        (root / "clean.log").write_text("kindnet watcher healthy\n", encoding="utf-8")
        value = subprocess.run([
            "python3", str(ENFORCEMENT), "preflight", "--daemonset", str(root / "ready-ds.json"),
            "--pods", str(root / "ready-pods.json"), "--logs", str(root / "clean.log"),
        ], capture_output=True, text=True)
        assert value.returncode == 0, value.stderr
        (root / "broken.log").write_text("Failed to watch *v1.Pod: i/o timeout\n", encoding="utf-8")
        value = subprocess.run([
            "python3", str(ENFORCEMENT), "preflight", "--daemonset", str(root / "ready-ds.json"),
            "--pods", str(root / "ready-pods.json"), "--logs", str(root / "broken.log"),
        ], capture_output=True, text=True)
        assert value.returncode != 0 and "watcher/API errors" in value.stderr

    content = (ROOT / "scripts/kindnet-policy-recover.sh").read_text(encoding="utf-8")
    assert content.count('cleanup-kubernetes-resource.py" cleanup') == 1
    assert "for IFS='|' read" not in content and "while IFS='|' read" in content
    assert content.index('confirm_exact "$kpr_confirmation"') < content.index("cleanup-kubernetes-resource.py")
    assert content.index("validate-kindnet-recovery.py\" preflight") < content.index('confirm_exact "$kpr_confirmation"')
    assert content.index("cleanup-kubernetes-resource.py") < content.index("test-kindnet-policy.sh")
    assert content.index("describe pod") < content.index("cleanup-kubernetes-resource.py")
    assert "Required confirmation: %s\\n" in content
    assert "-l app=kindnet" in content and "-l k8s-app=kindnet" not in content
    assert "--force" not in content and "rollout restart" not in content and "retry" not in content.lower()
    enforcement = (ROOT / "scripts/validate-kindnet-enforcement.py").read_text(encoding="utf-8")
    assert "Failed to watch" in enforcement and "i/o timeout" in enforcement
    print(
        "PASS  kindnet recovery requires the exact selector, template labels, direct ownership, "
        "runtime identity, readiness, node order, confirmation, and pre-confirmation safety."
    )


if __name__ == "__main__":
    main()
