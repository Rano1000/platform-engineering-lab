#!/usr/bin/env python3
"""Fail-closed discovery and rendering for kind's post-DNAT API endpoint."""

import argparse
import hashlib
import ipaddress
import json
import pathlib
import re
import sys

import yaml

NAMES = (
    "argocd-redis-secret-init-api",
    "argocd-application-controller-api",
    "argocd-server-api",
)
SELECTORS = {
    NAMES[0]: {"app.kubernetes.io/name": "argocd-redis-secret-init", "app.kubernetes.io/component": "redis-secret-init", "app.kubernetes.io/instance": "argocd"},
    NAMES[1]: {"app.kubernetes.io/name": "argocd-application-controller", "app.kubernetes.io/component": "application-controller", "app.kubernetes.io/instance": "argocd"},
    NAMES[2]: {"app.kubernetes.io/name": "argocd-server", "app.kubernetes.io/component": "server", "app.kubernetes.io/instance": "argocd"},
}


def fail(message):
    raise ValueError(message)


def load(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def discover(service, slices, node, apiserver, network, context, cluster):
    if context != "kind-platform-engineering-lab" or cluster != "platform-engineering-lab":
        fail("unexpected cluster identity")
    if service.get("metadata", {}).get("name") != "kubernetes" or service.get("metadata", {}).get("namespace") != "default":
        fail("unexpected Kubernetes Service")
    cluster_ip = service.get("spec", {}).get("clusterIP")
    ipaddress.IPv4Address(cluster_ip)
    service_ports = service.get("spec", {}).get("ports", [])
    if len(service_ports) != 1 or service_ports[0].get("protocol", "TCP") != "TCP" or service_ports[0].get("port") != 443:
        fail("Kubernetes Service must expose one TCP 443 port")
    items = slices.get("items", [])
    if len(items) != 1 or items[0].get("addressType") != "IPv4" or items[0].get("metadata", {}).get("labels", {}).get("kubernetes.io/service-name") != "kubernetes":
        fail("exactly one Kubernetes IPv4 EndpointSlice is required")
    endpoint_slice = items[0]
    endpoints = endpoint_slice.get("endpoints", [])
    if len(endpoints) != 1 or endpoints[0].get("conditions", {}).get("ready") is not True or len(endpoints[0].get("addresses", [])) != 1:
        fail("exactly one Ready API endpoint is required")
    endpoint_ip = str(ipaddress.IPv4Address(endpoints[0]["addresses"][0]))
    ports = endpoint_slice.get("ports", [])
    if len(ports) != 1 or ports[0].get("protocol", "TCP") != "TCP" or not isinstance(ports[0].get("port"), int):
        fail("exactly one numeric TCP API endpoint port is required")
    endpoint_port = ports[0]["port"]
    if endpoint_port != 6443:
        fail("kind kube-apiserver endpoint must use TCP 6443")
    node_meta = node.get("metadata", {})
    if node_meta.get("name") != "platform-engineering-lab-control-plane" or "node-role.kubernetes.io/control-plane" not in node_meta.get("labels", {}):
        fail("endpoint node is not the intended control plane")
    internal = [a.get("address") for a in node.get("status", {}).get("addresses", []) if a.get("type") == "InternalIP"]
    if internal != [endpoint_ip]:
        fail("API endpoint differs from the control-plane InternalIP")
    spec = apiserver.get("spec", {})
    status = apiserver.get("status", {})
    if spec.get("nodeName") != node_meta["name"] or spec.get("hostNetwork") is not True or status.get("hostIP") != endpoint_ip:
        fail("kube-apiserver host identity does not match the endpoint")
    containers = spec.get("containers", [])
    api_ports = [p for c in containers if c.get("name") == "kube-apiserver" for p in c.get("ports", []) if p.get("protocol", "TCP") == "TCP"]
    if not any(p.get("containerPort") == endpoint_port for p in api_ports):
        fail("kube-apiserver does not declare the discovered TCP port")
    if network.get("Name") != "kind" or not re.fullmatch(r"[0-9a-f]{64}", network.get("Id", "")):
        fail("unexpected kind Docker network identity")
    matches = []
    for container_id, attachment in network.get("Containers", {}).items():
        address = attachment.get("IPv4Address", "").split("/")[0]
        if attachment.get("Name") == node_meta["name"]:
            matches.append((container_id, address))
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0][0]) or matches[0][1] != endpoint_ip:
        fail("control-plane Docker network attachment does not match the endpoint")
    identity = {
        "schemaVersion": 1,
        "cluster": cluster,
        "context": context,
        "service": {"clusterIP": cluster_ip, "port": 443, "resourceVersion": service["metadata"].get("resourceVersion", "")},
        "endpointSlice": {"name": endpoint_slice["metadata"]["name"], "resourceVersion": endpoint_slice["metadata"].get("resourceVersion", "")},
        "apiEndpoint": {"address": endpoint_ip, "cidr": endpoint_ip + "/32", "port": endpoint_port, "ready": True},
        "controlPlane": {"name": node_meta["name"], "uid": node_meta.get("uid", ""), "internalIP": endpoint_ip},
        "apiServer": {"name": apiserver["metadata"]["name"], "uid": apiserver["metadata"].get("uid", ""), "hostIP": endpoint_ip, "port": endpoint_port},
        "dockerNetwork": {"name": "kind", "id": network["Id"], "containerId": matches[0][0], "address": endpoint_ip},
    }
    return identity


def render(template, identity):
    digest = hashlib.sha256(canonical(identity).encode()).hexdigest()
    result = template.replace("${API_ENDPOINT_CIDR}", identity["apiEndpoint"]["cidr"])
    result = result.replace("${API_ENDPOINT_PORT}", str(identity["apiEndpoint"]["port"]))
    result = result.replace("${ENDPOINT_IDENTITY_SHA256}", "sha256:" + digest)
    if "${" in result:
        fail("unresolved policy-template placeholder")
    validate_rendered_text(result, identity, digest)
    return result, digest


def validate_rendered_text(text, identity, digest):
    if "10.96.0.1/32" in text:
        fail("generated API policy is unexpectedly broad or uses a ClusterIP assumption")
    documents = list(yaml.safe_load_all(text))
    if len(documents) != 3 or [item.get("metadata", {}).get("name") for item in documents] != list(NAMES):
        fail("exactly three generated policies are required")
    for document in documents:
        name = document["metadata"]["name"]
        if document.get("apiVersion") != "networking.k8s.io/v1" or document.get("kind") != "NetworkPolicy" or document["metadata"].get("namespace") != "gitops":
            fail("generated policy identity is incomplete")
        if document["metadata"].get("annotations", {}).get("platform.engineering-lab/api-endpoint-identity-sha256") != "sha256:" + digest:
            fail("generated policy identity is incomplete")
        spec = document.get("spec", {})
        expected = [{"to": [{"ipBlock": {"cidr": identity["apiEndpoint"]["cidr"]}}], "ports": [{"protocol": "TCP", "port": identity["apiEndpoint"]["port"]}]}]
        if spec != {"podSelector": {"matchLabels": SELECTORS[name]}, "policyTypes": ["Egress"], "egress": expected}:
            fail("generated policy selector or endpoint is not exact")


def verify_live(live, identity, digest):
    items = sorted(live.get("items", []), key=lambda item: item.get("metadata", {}).get("name", ""))
    if [item.get("metadata", {}).get("name") for item in items] != sorted(NAMES):
        fail("live generated-policy set differs from the approved set")
    for item in items:
        name = item["metadata"]["name"]
        if item["metadata"].get("annotations", {}).get("platform.engineering-lab/api-endpoint-identity-sha256") != "sha256:" + digest:
            fail("live policy identity checksum differs")
        spec = item.get("spec", {})
        if spec.get("podSelector", {}).get("matchLabels") != SELECTORS[name] or spec.get("policyTypes") != ["Egress"]:
            fail("live policy selector or direction differs")
        expected = [{"to": [{"ipBlock": {"cidr": identity["apiEndpoint"]["cidr"]}}], "ports": [{"protocol": "TCP", "port": identity["apiEndpoint"]["port"]}]}]
        if spec.get("egress") != expected:
            fail("live API policy endpoint differs")
    protected = [{"name": item["metadata"]["name"], "annotations": {"platform.engineering-lab/api-endpoint-identity-sha256": item["metadata"]["annotations"]["platform.engineering-lab/api-endpoint-identity-sha256"]}, "spec": item["spec"]} for item in items]
    return hashlib.sha256(canonical(protected).encode()).hexdigest()


def self_test():
    ip = "172.18.0.4"
    service = {"metadata": {"name": "kubernetes", "namespace": "default", "resourceVersion": "1"}, "spec": {"clusterIP": "10.96.0.1", "ports": [{"port": 443, "protocol": "TCP"}]}}
    slices = {"items": [{"metadata": {"name": "kubernetes", "resourceVersion": "2", "labels": {"kubernetes.io/service-name": "kubernetes"}}, "addressType": "IPv4", "ports": [{"port": 6443, "protocol": "TCP"}], "endpoints": [{"addresses": [ip], "conditions": {"ready": True}}]}]}
    node = {"metadata": {"name": "platform-engineering-lab-control-plane", "uid": "n", "labels": {"node-role.kubernetes.io/control-plane": ""}}, "status": {"addresses": [{"type": "InternalIP", "address": ip}]}}
    api = {"metadata": {"name": "kube-apiserver-platform-engineering-lab-control-plane", "uid": "p"}, "spec": {"nodeName": node["metadata"]["name"], "hostNetwork": True, "containers": [{"name": "kube-apiserver", "ports": [{"containerPort": 6443, "protocol": "TCP"}]}]}, "status": {"hostIP": ip}}
    network = {"Name": "kind", "Id": "a" * 64, "Containers": {"b" * 64: {"Name": node["metadata"]["name"], "IPv4Address": ip + "/16"}}}
    identity = discover(service, slices, node, api, network, "kind-platform-engineering-lab", "platform-engineering-lab")
    template = pathlib.Path(__file__).resolve().parents[1] / "platform/addons/argocd/api-endpoint-policies.yaml.tpl"
    rendered, digest = render(template.read_text(), identity)
    assert len(digest) == 64 and rendered.count("kind: NetworkPolicy") == 3
    changed = json.loads(json.dumps(slices)); changed["items"][0]["metadata"]["resourceVersion"] = "3"
    for label, mutation in (("missing", []), ("multiple", slices["items"] * 2)):
        bad = json.loads(json.dumps(slices)); bad["items"] = mutation
        try: discover(service, bad, node, api, network, "kind-platform-engineering-lab", "platform-engineering-lab")
        except ValueError: pass
        else: fail(label + " endpoints accepted")
    bad = json.loads(json.dumps(slices)); bad["items"][0]["endpoints"][0]["conditions"]["ready"] = False
    try: discover(service, bad, node, api, network, "kind-platform-engineering-lab", "platform-engineering-lab")
    except ValueError: pass
    else: fail("non-Ready endpoint accepted")
    bad_network = json.loads(json.dumps(network)); next(iter(bad_network["Containers"].values()))["IPv4Address"] = "172.18.0.9/16"
    try: discover(service, slices, node, api, bad_network, "kind-platform-engineering-lab", "platform-engineering-lab")
    except ValueError: pass
    else: fail("Docker identity mismatch accepted")
    if discover(service, changed, node, api, network, "kind-platform-engineering-lab", "platform-engineering-lab") == identity:
        fail("snapshot race was not detected")
    for bad_template in (template.read_text().replace("${API_ENDPOINT_CIDR}", "0.0.0.0/0"), template.read_text().replace("port: ${API_ENDPOINT_PORT}", "port: ${API_ENDPOINT_PORT}, endPort: 65535"), template.read_text().replace("app.kubernetes.io/component: application-controller", "app.kubernetes.io/component: wrong")):
        try: render(bad_template, identity)
        except ValueError: pass
        else: fail("unsafe template accepted")
    print("PASS  Kubernetes API endpoint discovery and policy fixtures passed.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    discover_parser = sub.add_parser("render")
    for name in ("service", "endpoints", "node", "apiserver", "network", "template", "identity-output", "policy-output"):
        discover_parser.add_argument("--" + name, required=True)
    discover_parser.add_argument("--context", required=True)
    discover_parser.add_argument("--cluster", required=True)
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--expected", required=True); compare_parser.add_argument("--actual", required=True)
    live_parser = sub.add_parser("verify-live")
    live_parser.add_argument("--identity", required=True); live_parser.add_argument("--policies", required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test": self_test(); return
        if args.command == "compare":
            if canonical(load(args.expected)) != canonical(load(args.actual)): fail("protected API endpoint identity changed")
            print("PASS  API endpoint identity is unchanged."); return
        identity = load(args.identity) if args.command == "verify-live" else discover(load(args.service), load(args.endpoints), load(args.node), load(args.apiserver), load(args.network), args.context, args.cluster)
        digest = hashlib.sha256(canonical(identity).encode()).hexdigest()
        if args.command == "verify-live":
            policy_digest = verify_live(load(args.policies), identity, digest)
            print("PASS  live API policies match the endpoint identity; policy checksum sha256:" + policy_digest + ".")
            return
        rendered, digest = render(pathlib.Path(args.template).read_text(), identity)
        pathlib.Path(args.identity_output).write_text(canonical(identity))
        pathlib.Path(args.policy_output).write_text(rendered)
        print("sha256:" + digest)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("FAIL  " + str(error), file=sys.stderr); raise SystemExit(1)


if __name__ == "__main__":
    main()
