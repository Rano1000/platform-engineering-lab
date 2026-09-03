#!/usr/bin/env python3
"""Plan and verify an exact Argo API endpoint NetworkPolicy transition."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import pathlib
import re
import subprocess
import tempfile

import yaml

ANNOTATION = "platform.engineering-lab/api-endpoint-identity-sha256"
NAMES = (
    "argocd-redis-secret-init-api",
    "argocd-application-controller-api",
    "argocd-server-api",
)
ALLOWED_PATHS = (
    "/metadata/annotations/platform.engineering-lab~1api-endpoint-identity-sha256",
    "/spec/egress/0/to/0/ipBlock/cidr",
)


def fail(message: str) -> None:
    raise ValueError(message)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def checksum(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def load_json(path: str) -> object:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_yaml(path: str) -> list[dict]:
    return [item for item in yaml.safe_load_all(pathlib.Path(path).read_text(encoding="utf-8")) if item]


def atomic_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def normalized(item: dict) -> dict:
    return {
        "name": item["metadata"]["name"],
        "annotations": {ANNOTATION: item["metadata"].get("annotations", {}).get(ANNOTATION)},
        "spec": item.get("spec"),
    }


def indexed(items: list[dict]) -> dict[str, dict]:
    result = {item.get("metadata", {}).get("name", ""): item for item in items}
    if set(result) != set(NAMES) or len(items) != len(NAMES):
        fail("exactly the three approved NetworkPolicies are required")
    for name, item in result.items():
        metadata = item.get("metadata", {})
        if item.get("apiVersion") != "networking.k8s.io/v1" or item.get("kind") != "NetworkPolicy":
            fail(f"{name} has an unexpected API identity")
        if metadata.get("namespace") != "gitops" or not metadata.get("uid") or not metadata.get("resourceVersion"):
            fail(f"{name} live identity is incomplete")
    return result


def desired_index(items: list[dict]) -> dict[str, dict]:
    result = {item.get("metadata", {}).get("name", ""): item for item in items}
    if set(result) != set(NAMES) or len(items) != len(NAMES):
        fail("rendered output must contain exactly three approved policies")
    for name, item in result.items():
        if item.get("apiVersion") != "networking.k8s.io/v1" or item.get("kind") != "NetworkPolicy" or item.get("metadata", {}).get("namespace") != "gitops":
            fail(f"rendered policy {name} has an unexpected identity")
        validate_shape(item)
    return result


def validate_shape(item: dict) -> tuple[str, str]:
    metadata, spec = item.get("metadata", {}), item.get("spec", {})
    annotation = metadata.get("annotations", {}).get(ANNOTATION, "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", annotation):
        fail(f"{metadata.get('name')} has an invalid identity annotation")
    egress = spec.get("egress")
    try:
        cidr = egress[0]["to"][0]["ipBlock"]["cidr"]
        ports = egress[0]["ports"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError(f"{metadata.get('name')} has malformed egress") from error
    network = ipaddress.ip_network(cidr, strict=True)
    if network.version != 4 or network.prefixlen != 32:
        fail(f"{metadata.get('name')} endpoint CIDR is not an exact IPv4 /32")
    if len(egress) != 1 or len(egress[0].get("to", [])) != 1 or len(ports) != 1 or ports[0] != {"protocol": "TCP", "port": 6443}:
        fail(f"{metadata.get('name')} must allow only TCP 6443 without a port range")
    if spec.get("policyTypes") != ["Egress"] or not spec.get("podSelector", {}).get("matchLabels"):
        fail(f"{metadata.get('name')} selector or policy type is invalid")
    return annotation, cidr


def protected_without_allowed(item: dict) -> dict:
    value = json.loads(json.dumps(normalized(item)))
    value["annotations"].pop(ANNOTATION, None)
    value["spec"]["egress"][0]["to"][0]["ipBlock"].pop("cidr", None)
    return value


def plan(identity: dict, desired_items: list[dict], live_items: list[dict]) -> dict:
    desired, live = desired_index(desired_items), indexed(live_items)
    expected_identity = checksum(identity)
    desired_states = {validate_shape(item) for item in desired.values()}
    if len(desired_states) != 1:
        fail("rendered policies do not share one endpoint identity")
    new_annotation, new_cidr = next(iter(desired_states))
    if new_annotation != expected_identity or new_cidr != identity.get("apiEndpoint", {}).get("cidr"):
        fail("rendered policies do not match the verified endpoint identity")
    live_states = {validate_shape(item) for item in live.values()}
    if len(live_states) != 1:
        fail("mixed policy state requires explicit review")
    old_annotation, old_cidr = next(iter(live_states))
    records = []
    for name in NAMES:
        if protected_without_allowed(live[name]) != protected_without_allowed(desired[name]):
            fail(f"{name} contains an unexpected field difference")
        records.append({
            "name": name,
            "namespace": "gitops",
            "uid": live[name]["metadata"]["uid"],
            "resourceVersion": live[name]["metadata"]["resourceVersion"],
            "oldIdentityChecksum": old_annotation,
            "newIdentityChecksum": new_annotation,
            "oldCidr": old_cidr,
            "newCidr": new_cidr,
            "port": 6443,
            "allowedPaths": list(ALLOWED_PATHS),
            "patch": [
                {"op": "test", "path": "/metadata/uid", "value": live[name]["metadata"]["uid"]},
                {"op": "test", "path": "/metadata/resourceVersion", "value": live[name]["metadata"]["resourceVersion"]},
                {"op": "replace", "path": ALLOWED_PATHS[0], "value": new_annotation},
                {"op": "replace", "path": ALLOWED_PATHS[1], "value": new_cidr},
            ],
        })
    identity_changed = old_annotation != new_annotation
    cidr_changed = old_cidr != new_cidr
    if identity_changed != cidr_changed:
        fail("identity annotation and endpoint CIDR must transition together")
    state = "current" if not identity_changed else "transition"
    return {
        "schemaVersion": 1,
        "state": state,
        "oldIdentityChecksum": old_annotation,
        "newIdentityChecksum": new_annotation,
        "oldCidr": old_cidr,
        "newCidr": new_cidr,
        "desiredPolicyChecksum": checksum([normalized(desired[name]) for name in sorted(NAMES)]),
        "livePolicyChecksum": checksum([normalized(live[name]) for name in sorted(NAMES)]),
        "resources": records,
    }


def verify_pre(plan_value: dict, live_items: list[dict]) -> None:
    live = indexed(live_items)
    for record in plan_value["resources"]:
        item = live[record["name"]]
        if item["metadata"]["uid"] != record["uid"] or item["metadata"]["resourceVersion"] != record["resourceVersion"]:
            fail(f"{record['name']} UID or resourceVersion changed")
        annotation, cidr = validate_shape(item)
        if annotation != record["oldIdentityChecksum"] or cidr != record["oldCidr"]:
            fail(f"{record['name']} protected state changed")
    if checksum([normalized(live[name]) for name in sorted(NAMES)]) != plan_value["livePolicyChecksum"]:
        fail("live policy checksum changed")


def verify_after(plan_value: dict, identity: dict, live_items: list[dict]) -> str:
    live = indexed(live_items)
    for record in plan_value["resources"]:
        item = live[record["name"]]
        if item["metadata"]["uid"] != record["uid"]:
            fail(f"{record['name']} UID changed after reconciliation")
        annotation, cidr = validate_shape(item)
        if annotation != plan_value["newIdentityChecksum"] or cidr != plan_value["newCidr"]:
            fail(f"{record['name']} does not match the new endpoint")
    if checksum(identity) != plan_value["newIdentityChecksum"]:
        fail("post-apply endpoint identity changed")
    actual = checksum([normalized(live[name]) for name in sorted(NAMES)])
    if actual != plan_value["desiredPolicyChecksum"]:
        fail("final normalized live checksum differs")
    return actual


def write_plan(output: str, value: dict) -> None:
    root = pathlib.Path(output)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        fail("evidence output is unsafe")
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / "plan.json", value)
    for record in value["resources"]:
        atomic_json(root / f"patch-{record['name']}.json", record["patch"])


def finalize(root_raw: str) -> None:
    root = pathlib.Path(root_raw).resolve()
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            fail("evidence contains an unsafe path")
        if path.is_file() and path.name != "evidence-manifest.json":
            files[path.relative_to(root).as_posix()] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    atomic_json(root / "evidence-manifest.json", {"schemaVersion": 1, "files": files})


def apply_patches(plan_path: str, evidence_raw: str, kubectl: str, context: str) -> None:
    if context != "kind-platform-engineering-lab":
        fail("unexpected Kubernetes context")
    plan_value = load_json(plan_path)
    if plan_value.get("state") != "transition" or len(plan_value.get("resources", [])) != 3:
        fail("only a complete three-policy transition may be applied")
    if [record.get("name") for record in plan_value["resources"]] != list(NAMES):
        fail("apply plan contains an unexpected resource identity or order")
    plan_root = pathlib.Path(plan_path).resolve().parent
    evidence = pathlib.Path(evidence_raw)
    evidence.mkdir(parents=True, exist_ok=True)
    for record in plan_value["resources"]:
        name = record["name"]
        patch = plan_root / f"patch-{name}.json"
        if not patch.is_file() or patch.is_symlink():
            fail(f"approved patch is missing or unsafe: {name}")
        command = [kubectl, "--context", context, "patch", "networkpolicy", name, "--namespace", "gitops", "--type=json", "--patch-file", str(patch)]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        atomic_json(evidence / f"apply-{name}.json", {"name": name, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != 0:
            fail(f"single apply failed for {name}; no retry was attempted")


def fixture(ip: str, identity_char: str = "a") -> tuple[dict, list[dict]]:
    identity = {"apiEndpoint": {"cidr": ip + "/32"}}
    identity_digest = checksum(identity)
    docs = []
    selectors = ("redis-secret-init", "application-controller", "server")
    names = ("argocd-redis-secret-init", "argocd-application-controller", "argocd-server")
    for policy, component, app_name in zip(NAMES, selectors, names):
        docs.append({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": policy, "namespace": "gitops", "uid": identity_char * 8 + policy[-1], "resourceVersion": "10", "labels": {"app.kubernetes.io/managed-by": "platform-engineering-lab"}, "annotations": {ANNOTATION: identity_digest}}, "spec": {"podSelector": {"matchLabels": {"app.kubernetes.io/name": app_name, "app.kubernetes.io/component": component, "app.kubernetes.io/instance": "argocd"}}, "policyTypes": ["Egress"], "egress": [{"to": [{"ipBlock": {"cidr": ip + "/32"}}], "ports": [{"protocol": "TCP", "port": 6443}]}]}})
    return identity, docs


def rejected(function, label: str) -> None:
    try:
        function()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(label)


def self_test() -> None:
    old_identity, live = fixture("172.18.0.4")
    new_identity, desired = fixture("172.18.0.2", "b")
    value = plan(new_identity, desired, live)
    assert value["state"] == "transition" and value["oldCidr"] == "172.18.0.4/32"
    assert value["newCidr"] == "172.18.0.2/32" and value["oldIdentityChecksum"] == checksum(old_identity)
    assert all([item["path"] for item in record["patch"][-2:]] == list(ALLOWED_PATHS) for record in value["resources"])
    verify_pre(value, live)
    current = json.loads(json.dumps(desired))
    for index, item in enumerate(current):
        item["metadata"]["uid"] = live[index]["metadata"]["uid"]
        item["metadata"]["resourceVersion"] = "11"
    assert verify_after(value, new_identity, current) == value["desiredPolicyChecksum"]
    assert plan(new_identity, current, current)["state"] == "current"
    mixed = json.loads(json.dumps(live)); mixed[0]["spec"]["egress"][0]["to"][0]["ipBlock"]["cidr"] = "172.18.0.2/32"
    rejected(lambda: plan(new_identity, desired, mixed), "mixed state accepted")
    changed = json.loads(json.dumps(live)); changed[0]["spec"]["policyTypes"] = ["Ingress", "Egress"]
    rejected(lambda: plan(new_identity, desired, changed), "unexpected field accepted")
    broad = json.loads(json.dumps(desired)); broad[0]["spec"]["egress"][0]["to"][0]["ipBlock"]["cidr"] = "172.18.0.0/16"
    rejected(lambda: plan(new_identity, broad, live), "broad CIDR accepted")
    port = json.loads(json.dumps(desired)); port[0]["spec"]["egress"][0]["ports"][0]["port"] = 443
    rejected(lambda: plan(new_identity, port, live), "altered port accepted")
    raced = json.loads(json.dumps(live)); raced[0]["metadata"]["resourceVersion"] = "12"
    rejected(lambda: verify_pre(value, raced), "resourceVersion race accepted")
    uid = json.loads(json.dumps(live)); uid[0]["metadata"]["uid"] = "replacement"
    rejected(lambda: verify_pre(value, uid), "UID race accepted")
    changed_identity = json.loads(json.dumps(new_identity)); changed_identity["apiEndpoint"]["cidr"] = "172.18.0.9/32"
    rejected(lambda: verify_after(value, changed_identity, current), "snapshot C race accepted")
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        write_plan(str(root / "plan"), value)
        fake = root / "kubectl"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >>\"$FAKE_LOG\"\ncase $* in *argocd-application-controller-api*) exit 7;; esac\n")
        fake.chmod(0o700)
        log = root / "calls"
        old_log = os.environ.get("FAKE_LOG")
        os.environ["FAKE_LOG"] = str(log)
        try:
            rejected(lambda: apply_patches(str(root / "plan/plan.json"), str(root / "evidence"), str(fake), "kind-platform-engineering-lab"), "apply failure accepted")
        finally:
            if old_log is None: os.environ.pop("FAKE_LOG", None)
            else: os.environ["FAKE_LOG"] = old_log
        calls = log.read_text().splitlines()
        assert len(calls) == 2 and sum("argocd-application-controller-api" in call for call in calls) == 1
    print("PASS  API policy reconciliation accepts only an exact, race-free three-policy endpoint transition.")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    for name in ("identity", "desired", "live", "output"):
        plan_parser.add_argument("--" + name, required=True)
    pre = sub.add_parser("verify-pre")
    pre.add_argument("--plan", required=True); pre.add_argument("--live", required=True)
    after = sub.add_parser("verify-after")
    after.add_argument("--plan", required=True); after.add_argument("--identity", required=True); after.add_argument("--live", required=True)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--plan", required=True); apply_parser.add_argument("--evidence", required=True)
    apply_parser.add_argument("--kubectl", required=True); apply_parser.add_argument("--context", required=True)
    final = sub.add_parser("finalize-evidence"); final.add_argument("--root", required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test": self_test(); return
        if args.command == "plan":
            value = plan(load_json(args.identity), load_yaml(args.desired), load_json(args.live)["items"])
            write_plan(args.output, value); print(canonical(value), end=""); return
        if args.command == "verify-pre": verify_pre(load_json(args.plan), load_json(args.live)["items"]); print("PASS  live policy identities are unchanged."); return
        if args.command == "verify-after": print(verify_after(load_json(args.plan), load_json(args.identity), load_json(args.live)["items"])); return
        if args.command == "apply": apply_patches(args.plan, args.evidence, args.kubectl, args.context); print("PASS  each exact policy was applied once without retry."); return
        finalize(args.root); print("PASS  policy reconciliation evidence is checksummed.")
    except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
        raise SystemExit("FAIL  " + str(error)) from error


if __name__ == "__main__":
    main()
