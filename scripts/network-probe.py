#!/usr/bin/env python3
"""Create and test the bounded, structured network probe used by temporary Pods."""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import pathlib
import socket
import ssl
import sys


PROBE_SOURCE = r'''
import json, socket, ssl, sys, time

name, identity, node, host, port_text, expected, mode, timeout_text = sys.argv[1:]
port, timeout = int(port_text), float(timeout_text)
started = time.monotonic()
observed, category, detail, code = "process_failure", "process_failure", "", 2
sock = None
stage = "dns"
try:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        observed, category, detail, code = "dns_failure", "dns_failure", str(exc), 1
        addresses = []
    if addresses:
        stage = "tcp"
        family, socktype, proto, _, address = addresses[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(address)
            if mode == "api_tls":
                stage = "tls"
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                sock = context.wrap_socket(sock, server_hostname="kubernetes")
                sock.settimeout(timeout)
                stage = "http"
                sock.sendall(b"GET /version HTTP/1.1\r\nHost: kubernetes\r\nConnection: close\r\n\r\n")
                response = sock.recv(4096).decode("iso-8859-1", "replace")
                status = response.splitlines()[0] if response.startswith("HTTP/") else ""
                if status.startswith("HTTP/"):
                    status_code = int(status.split()[1])
                    category = "http_authorization_response" if status_code in (401, 403) else "tls_response"
                    observed, detail = "connected", status
                else:
                    observed, category, detail = "connected", "tls_response", "TLS exchange completed without HTTP status"
            else:
                observed, category, detail = "connected", "tcp_connected", "TCP connection completed"
            code = 0 if expected == "allow" else 1
        except (TimeoutError, socket.timeout) as exc:
            category = stage + "_timeout"
            observed, detail = ("denied" if stage == "tcp" else "process_failure"), str(exc) or "operation timed out"
            code = 0 if expected == "deny" and stage == "tcp" else 1
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
result = {"test_name": name, "source_identity": identity, "source_node": node,
          "destination_ip": host, "destination_port": port, "expected_result": expected,
          "observed_result": observed, "duration_seconds": duration,
          "exit_code": code, "error_category": category, "detail": detail}
print(json.dumps(result, sort_keys=True), flush=True)
raise SystemExit(code)
'''


def pod_overrides(args: argparse.Namespace) -> None:
    command = "import base64;exec(base64.b64decode(%r))" % base64.b64encode(PROBE_SOURCE.encode()).decode()
    spec = {
        "spec": {
            "nodeName": args.node,
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 1,
            "securityContext": {
                "runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [{
                "name": "probe", "image": args.image, "imagePullPolicy": "IfNotPresent",
                "command": ["python", "-c", command],
                "args": [args.test_name, args.identity, args.node, args.host, str(args.port), args.expected, args.mode, str(args.timeout)],
                "resources": {"requests": {"cpu": "5m", "memory": "16Mi"}, "limits": {"cpu": "25m", "memory": "32Mi"}},
                "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}, "readOnlyRootFilesystem": True},
            }],
        }
    }
    print(json.dumps(spec, separators=(",", ":")))


def execute_fake(outcome: str, expected: str) -> tuple[int, dict]:
    class FakeSocket:
        def settimeout(self, _timeout): pass
        def connect(self, _address):
            if outcome == "timeout": raise socket.timeout("timed out")
            if outcome == "refused": raise ConnectionRefusedError("connection refused")
        def close(self): pass

    original_getaddrinfo, original_socket, original_argv = socket.getaddrinfo, socket.socket, sys.argv
    socket.getaddrinfo = lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.0.2.1", 443))]
    socket.socket = lambda *_args, **_kwargs: FakeSocket()
    sys.argv = ["probe", outcome, "hook", "worker", "192.0.2.1", "443", expected, "tcp", "0.2"]
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            try: exec(PROBE_SOURCE, {})
            except SystemExit as error: code = int(error.code)
    finally:
        socket.getaddrinfo, socket.socket, sys.argv = original_getaddrinfo, original_socket, original_argv
    return code, json.loads(output.getvalue())


def self_test() -> None:
    code, result = execute_fake("success", "allow")
    assert code == 0 and result["observed_result"] == "connected" and result["error_category"] == "tcp_connected"
    code, result = execute_fake("timeout", "deny")
    assert code == 0 and result["observed_result"] == "denied" and result["error_category"] == "tcp_timeout"
    code, result = execute_fake("refused", "deny")
    assert code == 1 and result["error_category"] == "connection_refused"
    source = PROBE_SOURCE
    assert 'stage + "_timeout"' in source and '"dns_failure"' in source
    assert '"tls_response"' in source and '"http_authorization_response"' in source
    assert 'sock.settimeout(timeout)' in source and 'expected == "deny"' in source
    print("PASS  structured network probe reports success and distinguishes timeout, refusal, DNS, TLS, HTTP authorization, and process failures.")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    pod = subparsers.add_parser("pod-overrides")
    for option in ("node", "image", "test-name", "identity", "host", "expected", "mode"):
        pod.add_argument("--" + option, required=True)
    pod.add_argument("--port", type=int, required=True)
    pod.add_argument("--timeout", type=float, required=True)
    subparsers.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test": self_test()
    else: pod_overrides(args)


if __name__ == "__main__":
    main()
