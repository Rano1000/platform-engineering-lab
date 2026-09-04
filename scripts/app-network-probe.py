#!/usr/bin/env python3
"""Build and validate structured application NetworkPolicy probes."""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import socket
import ssl
import http.client
import urllib.error
import urllib.request


PROBE_SOURCE = r'''
import json, socket, ssl, sys, time

cases = json.loads(sys.argv[1])
failed = False
for case in cases:
    started = time.monotonic()
    observed, category, detail, code = "process_failure", "process_failure", "", 2
    sock = None
    stage = "dns"
    try:
        try:
            addresses = socket.getaddrinfo(case["host"], int(case["port"]), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            observed, category, detail, code = "dns_failure", "dns_failure", str(exc), 1
            addresses = []
        if addresses:
            stage = "tcp"
            family, socktype, proto, _, address = addresses[0]
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(float(case["timeout_seconds"]))
            try:
                sock.connect(address)
                if case["mode"] in ("http", "https"):
                    if case["mode"] == "https":
                        stage = "tls"
                        context = ssl.create_default_context()
                        sock = context.wrap_socket(sock, server_hostname=case["host"])
                        sock.settimeout(float(case["timeout_seconds"]))
                    stage = "http"
                    request = ("GET " + case["path"] + " HTTP/1.1\r\nHost: " + case["host"] +
                               "\r\nConnection: close\r\n\r\n").encode()
                    sock.sendall(request)
                    chunks = []
                    while True:
                        chunk = sock.recv(16384)
                        if not chunk: break
                        chunks.append(chunk)
                    response = b"".join(chunks).decode("utf-8", "replace")
                    first = response.splitlines()[0] if response.startswith("HTTP/") else ""
                    status = int(first.split()[1]) if first else 0
                    body = response.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in response else ""
                    if status != int(case["expected_status"]):
                        observed, category, detail, code = "unexpected_http_status", "unexpected_http_status", first, 1
                    elif case.get("body_contains") and case["body_contains"] not in body:
                        observed, category, detail, code = "unexpected_body", "unexpected_body", "required metric identity absent", 1
                    elif case["expected"] == "allow":
                        observed, category, detail, code = "allowed", "http_response", first, 0
                    else:
                        observed, category, detail, code = "unexpectedly_allowed", "http_response", first, 1
                else:
                    observed, category, detail = "connected", "tcp_connected", "TCP connection completed"
                    code = 0 if case["expected"] == "allow" else 1
            except (TimeoutError, socket.timeout) as exc:
                observed = "denied" if stage == "tcp" else "process_failure"
                category, detail = stage + "_timeout", str(exc) or "operation timed out"
                code = 0 if case["expected"] == "deny" and stage == "tcp" else 1
            except ConnectionRefusedError as exc:
                observed, category, detail, code = "refused", "connection_refused", str(exc), 1
            except ssl.SSLError as exc:
                observed, category, detail, code = "process_failure", "tls_failure", str(exc), 1
            except OSError as exc:
                observed, category, detail, code = "process_failure", "socket_error", str(exc), 2
    finally:
        if sock is not None:
            try: sock.close()
            except OSError: pass
    duration = round(time.monotonic() - started, 3)
    result = {"test_name": case["name"], "source_identity": case["identity"],
              "source_node": case["node"], "destination_ip": case["host"],
              "destination_port": int(case["port"]), "path": case.get("path", ""),
              "expected_result": case["expected"], "observed_result": observed,
              "duration_seconds": duration, "exit_code": code, "error_category": category,
              "detail": detail}
    print(json.dumps(result, sort_keys=True), flush=True)
    failed = failed or code != 0
raise SystemExit(1 if failed else 0)
'''

REQUIRED_KEYS = {
    "test_name", "source_identity", "source_node", "destination_ip", "destination_port",
    "expected_result", "observed_result", "duration_seconds", "exit_code", "error_category",
}
SHA256 = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


def classify_fixture(outcome: str, expected: str) -> tuple[str, str, int]:
    """Model the probe's fail-closed outcome policy for offline regression tests."""
    values = {
        "http_200": ("allowed", "http_response", 0 if expected == "allow" else 1),
        "timeout": ("denied", "tcp_timeout", 0 if expected == "deny" else 1),
        "refused": ("refused", "connection_refused", 1),
        "dns": ("dns_failure", "dns_failure", 1),
        "tls": ("process_failure", "tls_failure", 1),
        "status": ("unexpected_http_status", "unexpected_http_status", 1),
        "process": ("process_failure", "process_failure", 2),
    }
    return values[outcome]


def pod_overrides(args: argparse.Namespace) -> None:
    cases = json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise SystemExit("probe cases must be a non-empty array")
    for case in cases:
        case["node"] = args.node
        case["timeout_seconds"] = args.timeout
    command = "import base64;exec(base64.b64decode(%r))" % base64.b64encode(PROBE_SOURCE.encode()).decode()
    spec = {"spec": {
        "nodeName": args.node,
        "automountServiceAccountToken": False,
        "restartPolicy": "Never",
        "terminationGracePeriodSeconds": 1,
        "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{
            "name": "probe", "image": args.image, "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-c", command],
            "args": [json.dumps(cases, separators=(",", ":"))],
            "resources": {"requests": {"cpu": "5m", "memory": "16Mi"},
                          "limits": {"cpu": "25m", "memory": "32Mi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
                                "readOnlyRootFilesystem": True},
        }],
    }}
    print(json.dumps(spec, separators=(",", ":")))


def listener_overrides(args: argparse.Namespace) -> None:
    assert SHA256.fullmatch(args.image) and 1024 <= args.port <= 65535
    source = "import socket;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',int(__import__('sys').argv[1])));s.listen();print('listener_ready',flush=True);exec('while True:\\n c,_=s.accept()\\n c.close()\\n print(\"connection_accepted\",flush=True)')"
    spec = {"spec": {"nodeName": args.node, "automountServiceAccountToken": False,
        "terminationGracePeriodSeconds": 1,
        "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{"name": "listener", "image": args.image, "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-c", source], "args": [str(args.port)],
            "ports": [{"containerPort": args.port}],
            "resources": {"requests": {"cpu": "5m", "memory": "16Mi"},
                          "limits": {"cpu": "25m", "memory": "32Mi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
                                "readOnlyRootFilesystem": True}}]}}
    print(json.dumps(spec, separators=(",", ":")))


def validate_log(args: argparse.Namespace) -> None:
    expected = json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    lines = [json.loads(line) for line in pathlib.Path(args.log).read_text(encoding="utf-8").splitlines() if line.strip()]
    pod = json.loads(pathlib.Path(args.pod).read_text(encoding="utf-8"))
    if len(lines) != len(expected):
        raise SystemExit("probe did not emit one result per assertion")
    print(json.dumps(lines, sort_keys=True, separators=(",", ":")), flush=True)
    if pod["metadata"]["uid"] != args.uid or pod["spec"]["nodeName"] != args.node:
        raise SystemExit("probe Pod identity or placement changed")
    terminated = pod.get("status", {}).get("containerStatuses", [{}])[0].get("state", {}).get("terminated", {})
    for wanted, result in zip(expected, lines, strict=True):
        if not REQUIRED_KEYS.issubset(result):
            raise SystemExit("probe result is incomplete")
        identity = (wanted["name"], wanted["identity"], args.node, wanted["host"], int(wanted["port"]), wanted["expected"])
        actual = (result["test_name"], result["source_identity"], result["source_node"],
                  result["destination_ip"], result["destination_port"], result["expected_result"])
        if actual != identity or result["duration_seconds"] >= args.outer_timeout:
            raise SystemExit("probe result identity or timeout boundary changed")
        if result["exit_code"] != 0:
            raise SystemExit("probe assertion failed: " + json.dumps(result, sort_keys=True))
    if terminated.get("exitCode") != 0:
        raise SystemExit("probe suite container did not terminate successfully")


def host_http_result(args: argparse.Namespace, opener=urllib.request.urlopen) -> tuple[dict, int]:
    started = __import__("time").monotonic()
    status, category, detail, code = 0, "process_failure", "", 2
    request = urllib.request.Request(args.url, headers={"Host": args.host_header})
    try:
        with opener(request, timeout=args.timeout) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        category = "expected_http_error" if status == args.expected_status else "unexpected_http_status"
        detail = f"HTTP {status}"
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, socket.gaierror):
            category = "dns_failure"
        elif isinstance(reason, ConnectionRefusedError):
            category = "connection_refused"
        elif isinstance(reason, (socket.timeout, TimeoutError)):
            category = "tcp_connect_timeout"
        elif isinstance(reason, ssl.SSLError):
            category = "tls_failure"
        else:
            category = "connection_failure"
        detail, code = str(reason), 1
    except (socket.timeout, TimeoutError) as error:
        category, detail, code = "http_read_timeout", str(error) or "HTTP read timed out", 1
    except ConnectionRefusedError as error:
        category, detail, code = "connection_refused", str(error), 1
    except socket.gaierror as error:
        category, detail, code = "dns_failure", str(error), 1
    except ssl.SSLError as error:
        category, detail, code = "tls_failure", str(error), 1
    except (http.client.BadStatusLine, http.client.HTTPException) as error:
        category, detail, code = "malformed_response", str(error), 1
    except Exception as error:  # Always emit one result for operational failures.
        category, detail, code = "process_failure", f"{type(error).__name__}: {error}", 2
    if status:
        if category == "process_failure":
            category = "http_success" if status < 400 else "expected_http_error"
        detail = f"HTTP {status}"
        code = 0 if status == args.expected_status else 1
        if code:
            category = "unexpected_http_status"
    result = {"test_name": args.name, "source_identity": "localhost", "source_node": "workstation",
              "destination_ip": "127.0.0.1", "destination_port": 80, "path": args.url,
              "expected_result": f"http_{args.expected_status}", "observed_result": f"http_{status}",
              "duration_seconds": round(__import__("time").monotonic() - started, 3),
              "exit_code": code, "error_category": category, "detail": detail}
    return result, code


def host_http(args: argparse.Namespace) -> None:
    result, code = host_http_result(args)
    print(json.dumps(result, sort_keys=True), flush=True)
    raise SystemExit(code)


def self_test() -> None:
    assert SHA256.fullmatch("ghcr.io/example/app@sha256:" + "a" * 64)
    assert "socket.timeout" in PROBE_SOURCE and "connection_refused" in PROBE_SOURCE
    assert "dns_failure" in PROBE_SOURCE and "unexpected_http_status" in PROBE_SOURCE
    assert "http_response" in PROBE_SOURCE and "process_failure" in PROBE_SOURCE
    assert 'case["expected"] == "deny" and stage == "tcp"' in PROBE_SOURCE
    assert 'duration_seconds' in PROBE_SOURCE and 'failed = failed or code != 0' in PROBE_SOURCE
    assert classify_fixture("http_200", "allow") == ("allowed", "http_response", 0)
    assert classify_fixture("timeout", "deny") == ("denied", "tcp_timeout", 0)
    assert classify_fixture("timeout", "allow")[2] == 1
    for outcome, category, code in (
        ("refused", "connection_refused", 1), ("dns", "dns_failure", 1),
        ("tls", "tls_failure", 1), ("status", "unexpected_http_status", 1),
        ("process", "process_failure", 2),
    ):
        result = classify_fixture(outcome, "deny")
        assert result[1:] == (category, code)
    fixture = argparse.Namespace(url="http://invalid/", host_header="example", timeout=0.1,
                                 expected_status=404, name="fixture")
    class Response:
        status = 404
        def __enter__(self): return self
        def __exit__(self, *_args): return False
    result, code = host_http_result(fixture, lambda *_args, **_kwargs: Response())
    assert code == 0 and result["error_category"] == "expected_http_error"
    for error, category, expected_code in (
        (urllib.error.HTTPError(fixture.url, 503, "bad", {}, None), "unexpected_http_status", 1),
        (urllib.error.URLError(socket.gaierror("dns")), "dns_failure", 1),
        (urllib.error.URLError(ConnectionRefusedError("refused")), "connection_refused", 1),
        (urllib.error.URLError(socket.timeout("connect")), "tcp_connect_timeout", 1),
        (urllib.error.URLError(ssl.SSLError("tls")), "tls_failure", 1),
        (http.client.BadStatusLine("bad"), "malformed_response", 1),
        (RuntimeError("process"), "process_failure", 2),
    ):
        def raising(*_args, error=error, **_kwargs): raise error
        result, code = host_http_result(fixture, raising)
        assert code == expected_code and result["error_category"] == category
    for error in (TimeoutError("read timed out"), socket.timeout("socket timed out")):
        def raising(*_args, error=error, **_kwargs): raise error
        result, code = host_http_result(fixture, raising)
        assert code == 1 and result["error_category"] == "http_read_timeout"
        assert set(result) == {"test_name", "source_identity", "source_node", "destination_ip",
            "destination_port", "path", "expected_result", "observed_result", "duration_seconds",
            "exit_code", "error_category", "detail"}
    print("PASS  application network probes classify HTTP, denial timeout, refusal, DNS, socket, and process outcomes independently.")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    pod = commands.add_parser("pod-overrides")
    pod.add_argument("--node", required=True); pod.add_argument("--image", required=True)
    pod.add_argument("--cases", required=True); pod.add_argument("--timeout", type=float, required=True)
    listener = commands.add_parser("listener-overrides")
    listener.add_argument("--node", required=True); listener.add_argument("--image", required=True)
    listener.add_argument("--port", type=int, required=True)
    validate = commands.add_parser("validate-log")
    validate.add_argument("--cases", required=True); validate.add_argument("--log", required=True)
    validate.add_argument("--pod", required=True); validate.add_argument("--uid", required=True)
    validate.add_argument("--node", required=True); validate.add_argument("--outer-timeout", type=float, required=True)
    host = commands.add_parser("host-http")
    host.add_argument("--name", required=True); host.add_argument("--url", required=True)
    host.add_argument("--host-header", required=True); host.add_argument("--expected-status", type=int, required=True)
    host.add_argument("--timeout", type=float, required=True)
    commands.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "pod-overrides": pod_overrides(args)
    elif args.command == "listener-overrides": listener_overrides(args)
    elif args.command == "validate-log": validate_log(args)
    elif args.command == "host-http": host_http(args)
    else: self_test()


if __name__ == "__main__":
    main()
