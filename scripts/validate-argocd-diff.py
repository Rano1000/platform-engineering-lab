#!/usr/bin/env python3
"""Validate the bounded resource changes emitted by Argo CD app diff."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tempfile

import yaml

DIFF_EXIT_CODE = 20
HEADER = re.compile(r"^===== (?P<kind>\S+) (?P<identity>\S+) ======$")
COMMAND = re.compile(r"^(?P<left>\d+(?:,\d+)?)(?P<operation>[acd])(?P<right>\d+(?:,\d+)?)$")
ROOT_IDENTITY = ("argoproj.io/Application", "gitops/golden-path-api")
CHILD_IDENTITIES = {
    ("apps/Deployment", "platform-apps/golden-path-golden-path-api"),
    ("gateway.networking.k8s.io/HTTPRoute", "platform-apps/golden-path-golden-path-api"),
    ("networking.k8s.io/NetworkPolicy", "observability/golden-path-golden-path-api-metrics-test-egress"),
    ("networking.k8s.io/NetworkPolicy", "platform-apps/golden-path-golden-path-api-allow-approved-ingress"),
    ("policy/PodDisruptionBudget", "platform-apps/golden-path-golden-path-api"),
    ("/ConfigMap", "platform-apps/golden-path-golden-path-api"),
    ("/Service", "platform-apps/golden-path-golden-path-api"),
    ("/ServiceAccount", "platform-apps/golden-path-golden-path-api"),
}
REDACTIONS = (
    (re.compile(r"(?i)(authorization:\s*(?:bearer\s+)?)[^\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:token|password|client-key-data)\s*[=:]\s*)[^\s]+"), r"\1[REDACTED]"),
)


class DiffValidationError(RuntimeError):
    pass


def sanitize(value: str) -> str:
    sanitized = value
    for pattern, replacement in REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized[:8000]


def split_sections(output: str) -> list[tuple[tuple[str, str], list[str]]]:
    sections: list[tuple[tuple[str, str], list[str]]] = []
    current: tuple[str, str] | None = None
    body: list[str] = []
    for line in output.splitlines():
        match = HEADER.fullmatch(line)
        if match:
            if current is not None:
                sections.append((current, body))
            current = (match.group("kind"), match.group("identity"))
            body = []
        elif current is None:
            if line.strip():
                raise DiffValidationError("unexpected output appeared before the first resource header")
        else:
            body.append(line)
    if current is not None:
        sections.append((current, body))
    if not sections:
        raise DiffValidationError("diff output contains no resource section")
    if len({identity for identity, _ in sections}) != len(sections):
        raise DiffValidationError("diff output repeats a resource section")
    return sections


def classify(body: list[str]) -> str:
    operations: list[str] = []
    payload = False
    for line in body:
        match = COMMAND.fullmatch(line)
        if match:
            operations.append(match.group("operation"))
        elif line.startswith(("> ", "< ")):
            payload = True
        elif line in ("---", "\\ No newline at end of file") or not line:
            continue
        else:
            raise DiffValidationError(f"unrecognized diff line: {line!r}")
    if not operations or not payload:
        raise DiffValidationError("resource section has no complete diff hunk")
    unique = set(operations)
    if unique == {"a"} and not any(line.startswith("< ") for line in body):
        return "creation"
    if unique == {"d"} and not any(line.startswith("> ") for line in body):
        return "deletion"
    if "c" in unique or unique == {"a", "d"}:
        return "modification"
    raise DiffValidationError("resource section has ambiguous change semantics")


def validate_root(sections: list[tuple[tuple[str, str], list[str]]], expected: pathlib.Path) -> None:
    if len(sections) != 1 or sections[0][0] != ROOT_IDENTITY:
        raise DiffValidationError("root diff must create exactly Application/gitops/golden-path-api")
    if classify(sections[0][1]) != "creation":
        raise DiffValidationError("root diff must be a creation, never a modification or deletion")
    rendered = "\n".join(line[2:] for line in sections[0][1] if line.startswith("> ")) + "\n"
    try:
        proposed = yaml.safe_load(rendered)
        approved = yaml.safe_load(expected.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise DiffValidationError(f"unable to parse the complete proposed Application: {error}") from error
    if proposed != approved:
        raise DiffValidationError("proposed child Application does not match the approved immutable manifest")


def validate_child(sections: list[tuple[tuple[str, str], list[str]]]) -> None:
    for identity, body in sections:
        if identity not in CHILD_IDENTITIES:
            raise DiffValidationError(f"child diff contains an unapproved resource: {identity[0]} {identity[1]}")
        if classify(body) == "deletion":
            raise DiffValidationError(f"child diff proposes an unapproved deletion: {identity[0]} {identity[1]}")


def validate(mode: str, status: int, stdout: str, stderr: str, expected: pathlib.Path | None) -> None:
    if status == 0:
        raise DiffValidationError("Argo reported no differences; there is no guarded change to approve")
    if status != DIFF_EXIT_CODE:
        detail = sanitize(stderr.strip() or stdout.strip() or "no diagnostic output")
        raise DiffValidationError(f"Argo operational failure (exit {status}): {detail}")
    if stderr.strip():
        raise DiffValidationError(f"Argo diff returned unexpected diagnostics: {sanitize(stderr.strip())}")
    sections = split_sections(stdout)
    if mode == "root":
        if expected is None:
            raise DiffValidationError("root diff validation requires the approved child manifest")
        validate_root(sections, expected)
    else:
        validate_child(sections)


def fixture(identity: tuple[str, str], operation: str, content: str = "kind: ConfigMap") -> str:
    lines = content.splitlines()
    command = {"a": f"0a1,{len(lines)}", "c": "1c1", "d": f"1,{len(lines)}d0"}[operation]
    prefix = "<" if operation == "d" else ">"
    payload = "\n".join(f"{prefix} {line}" for line in lines)
    return f"\n===== {identity[0]} {identity[1]} ======\n{command}\n{payload}\n"


def expect_failure(action, label: str) -> None:
    try:
        action()
    except DiffValidationError:
        return
    raise AssertionError(f"{label} was accepted")


def self_test() -> None:
    approved = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": "golden-path-api", "namespace": "gitops"},
    }
    with tempfile.TemporaryDirectory(prefix="argocd-diff-self-test-") as temporary:
        expected = pathlib.Path(temporary) / "approved.yaml"
        expected.write_text(yaml.safe_dump(approved, sort_keys=False), encoding="utf-8")
        output = fixture(ROOT_IDENTITY, "a", yaml.safe_dump(approved, sort_keys=False).rstrip())
        validate("root", DIFF_EXIT_CODE, output, "", expected)
        expect_failure(lambda: validate("root", 0, "", "", expected), "empty diff")
        expect_failure(lambda: validate("root", DIFF_EXIT_CODE, fixture(("/ConfigMap", "gitops/other"), "a"), "", expected), "unexpected creation")
        expect_failure(lambda: validate("root", DIFF_EXIT_CODE, fixture(ROOT_IDENTITY, "c"), "", expected), "modification")
        expect_failure(lambda: validate("root", DIFF_EXIT_CODE, fixture(ROOT_IDENTITY, "d"), "", expected), "deletion")
        expect_failure(lambda: validate("root", DIFF_EXIT_CODE, output + fixture(("/ConfigMap", "gitops/other"), "a"), "", expected), "multiple resources")
        expect_failure(lambda: validate("root", 2, "", "authentication failed", expected), "operational failure")
        expect_failure(lambda: validate("root", DIFF_EXIT_CODE, "ambiguous", "", expected), "ambiguous output")
    child = next(iter(CHILD_IDENTITIES))
    validate("child", DIFF_EXIT_CODE, fixture(child, "c"), "", None)
    expect_failure(lambda: validate("child", DIFF_EXIT_CODE, fixture(child, "d"), "", None), "child deletion")
    print("PASS  Argo diff validation separates expected changes from empty, unsafe, ambiguous, and operational outcomes.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--mode", choices=("root", "child"))
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--stdout", type=pathlib.Path)
    parser.add_argument("--stderr", type=pathlib.Path)
    parser.add_argument("--expected", type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        if args.mode is None or args.exit_code is None or args.stdout is None or args.stderr is None:
            raise DiffValidationError("mode, exit-code, stdout, and stderr are required")
        validate(
            args.mode,
            args.exit_code,
            args.stdout.read_text(encoding="utf-8"),
            args.stderr.read_text(encoding="utf-8"),
            args.expected,
        )
        print(f"PASS  guarded {args.mode} diff contains only the approved resource changes.")
        return 0
    except (DiffValidationError, OSError, UnicodeError) as error:
        print(f"FAIL  {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
