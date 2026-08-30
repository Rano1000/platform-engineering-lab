#!/usr/bin/env python3
"""Validate Argo CD diffs and retain deterministic, sanitized evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / ".artifacts/gitops-diff"
DIFF_EXIT_CODE = 20
HEADER = re.compile(r"^===== (?P<kind>\S+) (?P<identity>\S+) ======$")
COMMAND = re.compile(r"^\d+(?:,\d+)?(?P<operation>[acd])\d+(?:,\d+)?$")
SAFE_EVIDENCE_NAME = re.compile(r"^[0-9]+-[0-9]+-[0-9]+-(?:root|child)$")
ROOT_IDENTITY = ("argoproj.io/Application", "gitops/golden-path-api")
ROOT_APPLICATION = "platform-environment"
TRACKING_ANNOTATION = "argocd.argoproj.io/tracking-id"
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
SENSITIVE_KEY = re.compile(r"(?i)(?:token|password|secret|client-key|private-key|authorization)")
TEXT_REDACTIONS = (
    (re.compile(r"(?i)(authorization:\s*(?:bearer\s+)?)[^\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:token|password|client-key-data|private-key-data)\s*[=:]\s*)[^\s]+"), r"\1[REDACTED]"),
)
DEFAULTED_POINTERS = {
    "/spec/source/helm/passCredentials", "/spec/source/helm/skipCrds",
    "/spec/source/helm/ignoreMissingValueFiles", "/spec/destination/name",
}
MISSING = object()


class DiffValidationError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently keeping the last value."""


def construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate YAML key: {key}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping)


def sanitize_text(value: str, limit: int | None = None) -> str:
    result = value
    for pattern, replacement in TEXT_REDACTIONS:
        result = pattern.sub(replacement, result)
    return result if limit is None else result[:limit]


def redact_value(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {item: redact_value(child, item) for item, child in sorted(value.items())}
    if isinstance(value, list):
        return [redact_value(child) for child in value]
    return sanitize_text(value) if isinstance(value, str) else value


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def pointer(parent: str, item: str | int) -> str:
    token = str(item).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{token}"


def empty_representation(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def difference_classification(path: str, expected: Any, proposed: Any, state: str) -> str:
    if state in ("missing", "additional"):
        present = proposed if expected is MISSING else expected
        if empty_representation(present):
            return "representation_difference"
    if state == "additional" and (path == "/metadata" or path.startswith("/metadata/")):
        return "metadata_added_by_argo"
    if state == "additional" and path in DEFAULTED_POINTERS:
        return "kubernetes_or_argo_defaulted"
    return "genuine_desired_specification_change"


def make_difference(path: str, expected: Any, proposed: Any, state: str) -> dict[str, Any]:
    return {
        "path": path, "state": state,
        "classification": difference_classification(path, expected, proposed, state),
        "expected": "[MISSING]" if expected is MISSING else redact_value(expected),
        "proposed": "[MISSING]" if proposed is MISSING else redact_value(proposed),
    }


def compare(expected: Any, proposed: Any, path: str = "") -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    if isinstance(expected, dict) and isinstance(proposed, dict):
        for key in sorted(set(expected) | set(proposed)):
            child = pointer(path, key)
            if key not in expected:
                differences.append(make_difference(child, MISSING, proposed[key], "additional"))
            elif key not in proposed:
                differences.append(make_difference(child, expected[key], MISSING, "missing"))
            else:
                differences.extend(compare(expected[key], proposed[key], child))
        return differences
    if isinstance(expected, list) and isinstance(proposed, list):
        for index in range(max(len(expected), len(proposed))):
            child = pointer(path, index)
            if index >= len(expected):
                differences.append(make_difference(child, MISSING, proposed[index], "additional"))
            elif index >= len(proposed):
                differences.append(make_difference(child, expected[index], MISSING, "missing"))
            else:
                differences.extend(compare(expected[index], proposed[index], child))
        return differences
    if type(expected) is not type(proposed) or expected != proposed:
        differences.append(make_difference(path or "/", expected, proposed, "changed"))
    return differences


def atomic_write(path: pathlib.Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class Evidence:
    def __init__(self, destination: pathlib.Path):
        if destination.parent != EVIDENCE_ROOT or not SAFE_EVIDENCE_NAME.fullmatch(destination.name):
            raise DiffValidationError("diff evidence destination is outside the unique ignored evidence root")
        EVIDENCE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        if EVIDENCE_ROOT.is_symlink() or not EVIDENCE_ROOT.is_dir():
            raise DiffValidationError("diff evidence root is not a safe directory")
        os.mkdir(destination, mode=0o700)
        if destination.is_symlink() or not destination.is_dir():
            raise DiffValidationError("diff evidence run path is not a safe directory")
        self.destination, self.files, self.completed = destination, [], False

    def write_text(self, name: str, value: str) -> None:
        self.write_bytes(name, value.encode("utf-8"))

    def write_json(self, name: str, value: Any) -> None:
        self.write_text(name, json.dumps(redact_value(canonical(value)), sort_keys=True, separators=(",", ":")) + "\n")

    def write_bytes(self, name: str, value: bytes) -> None:
        if pathlib.PurePath(name).name != name or not re.fullmatch(r"[a-z0-9.-]+", name):
            raise DiffValidationError("unsafe evidence filename")
        path = self.destination / name
        atomic_write(path, value)
        if path.is_symlink() or not path.is_file() or not os.access(path, os.R_OK):
            raise DiffValidationError(f"evidence file is unsafe or unreadable: {name}")
        self.files.append(name)

    def complete(self, status: int, outcome: str) -> None:
        checksums = {name: hashlib.sha256((self.destination / name).read_bytes()).hexdigest() for name in sorted(self.files)}
        self.write_json("evidence-manifest.json", {"schemaVersion": 1, "outcome": outcome, "argoExitCode": status, "files": checksums})
        required = set(checksums) | {"evidence-manifest.json"}
        entries = list(self.destination.iterdir())
        if {item.name for item in entries} != required or any(item.is_symlink() or not item.is_file() for item in entries):
            raise DiffValidationError("diff diagnostic evidence is incomplete or contains unsafe entries")
        self.completed = True


def split_sections(output: str) -> list[tuple[tuple[str, str], list[str]]]:
    sections, body, current = [], [], None
    for line in output.splitlines():
        match = HEADER.fullmatch(line)
        if match:
            if current is not None:
                sections.append((current, body))
            current, body = (match.group("kind"), match.group("identity")), []
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
    operations, payload = [], False
    for line in body:
        match = COMMAND.fullmatch(line)
        if match: operations.append(match.group("operation"))
        elif line.startswith(("> ", "< ")): payload = True
        elif line in ("---", "\\ No newline at end of file") or not line: continue
        else: raise DiffValidationError(f"unrecognized diff line: {line!r}")
    if not operations or not payload:
        raise DiffValidationError("resource section has no complete diff hunk")
    unique = set(operations)
    if unique == {"a"} and not any(line.startswith("< ") for line in body): return "creation"
    if unique == {"d"} and not any(line.startswith("> ") for line in body): return "deletion"
    if "c" in unique or unique == {"a", "d"}: return "modification"
    raise DiffValidationError("resource section has ambiguous change semantics")


def protected_checksum(application: dict[str, Any]) -> str:
    specification = application.get("spec")
    if not isinstance(specification, dict):
        raise DiffValidationError("approved child Application has no complete specification")
    return hashlib.sha256(json.dumps(canonical(specification), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def required_tracking_identity() -> tuple[str, dict[str, str]]:
    group_kind, namespace_name = ROOT_IDENTITY
    group, kind = group_kind.split("/", 1)
    namespace, name = namespace_name.split("/", 1)
    components = {
        "managingRoot": ROOT_APPLICATION,
        "apiGroup": group,
        "kind": kind,
        "namespace": namespace,
        "resourceName": name,
    }
    value = f"{ROOT_APPLICATION}:{group}/{kind}:{namespace}/{name}"
    return value, components


def normalize_tracking_annotation(approved: dict[str, Any], proposed: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    approved_annotations = approved.get("metadata", {}).get("annotations", {})
    if not isinstance(approved_annotations, dict):
        raise DiffValidationError("repository Application annotations are malformed")
    if TRACKING_ANNOTATION in approved_annotations:
        raise DiffValidationError("repository Application must not supply Argo's runtime tracking annotation")
    proposed_annotations = proposed.get("metadata", {}).get("annotations", {})
    if not isinstance(proposed_annotations, dict):
        raise DiffValidationError("proposed Application annotations are malformed")
    required_value, components = required_tracking_identity()
    actual = proposed_annotations.get(TRACKING_ANNOTATION, MISSING)
    if actual is MISSING:
        raise DiffValidationError("Argo proposal is missing its required deterministic tracking annotation")
    if not isinstance(actual, str) or actual != required_value:
        raise DiffValidationError(
            f"Argo tracking identity is altered; expected {required_value!r}, proposed {redact_value(actual)!r}"
        )
    normalized = copy.deepcopy(proposed)
    del normalized["metadata"]["annotations"][TRACKING_ANNOTATION]
    if not normalized["metadata"]["annotations"] and "annotations" not in approved.get("metadata", {}):
        del normalized["metadata"]["annotations"]
    decision = {
        "decision": "accepted_exact_argo_tracking_metadata",
        "annotation": TRACKING_ANNOTATION,
        "value": required_value,
        "components": components,
        "scope": "root_diff_proposed_child_only",
    }
    return normalized, decision


def parse_root(sections: list[tuple[tuple[str, str], list[str]]]) -> dict[str, Any]:
    if len(sections) != 1 or sections[0][0] != ROOT_IDENTITY:
        raise DiffValidationError("root diff must create exactly Application/gitops/golden-path-api")
    if classify(sections[0][1]) != "creation":
        raise DiffValidationError("root diff must be a creation, never a modification or deletion")
    rendered = "\n".join(line[2:] for line in sections[0][1] if line.startswith("> ")) + "\n"
    try: proposed = yaml.load(rendered, Loader=UniqueKeyLoader)
    except yaml.YAMLError as error: raise DiffValidationError(f"unable to parse the complete proposed Application: {error}") from error
    if not isinstance(proposed, dict): raise DiffValidationError("parsed proposed Application is not an object")
    return proposed


def validate_child(sections: list[tuple[tuple[str, str], list[str]]]) -> None:
    for identity, body in sections:
        if identity not in CHILD_IDENTITIES:
            raise DiffValidationError(f"child diff contains an unapproved resource: {identity[0]} {identity[1]}")
        if classify(body) == "deletion":
            raise DiffValidationError(f"child diff proposes an unapproved deletion: {identity[0]} {identity[1]}")


def validate(mode: str, status: int, stdout: str, stderr: str, expected_path: pathlib.Path | None,
             expected_checksum: str | None, evidence: Evidence) -> None:
    evidence.write_text("argocd-diff.txt", sanitize_text(stdout))
    evidence.write_text("argocd-stderr.txt", sanitize_text(stderr))
    evidence.write_json("command-result.json", {"argoExitCode": status, "mode": mode})
    if status == 0:
        evidence.complete(status, "no_diff")
        raise DiffValidationError("Argo reported no differences; there is no guarded change to approve")
    if status != DIFF_EXIT_CODE:
        evidence.complete(status, "operational_failure")
        detail = sanitize_text(stderr.strip() or stdout.strip() or "no diagnostic output", 8000)
        raise DiffValidationError(f"Argo operational failure (exit {status}): {detail}", status)
    if stderr.strip():
        evidence.complete(status, "unexpected_stderr")
        raise DiffValidationError(f"Argo diff returned unexpected diagnostics: {sanitize_text(stderr.strip(), 8000)}")
    sections = split_sections(stdout)
    if mode == "child":
        validate_child(sections)
        evidence.write_json("resource-sections.json", [{"kind": item[0][0], "identity": item[0][1]} for item in sections])
        evidence.complete(status, "approved_diff"); return
    if expected_path is None or expected_checksum is None or not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
        raise DiffValidationError("root diff requires the complete protected child specification checksum")
    try: approved = yaml.load(expected_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as error: raise DiffValidationError(f"unable to parse the approved Application: {error}") from error
    if not isinstance(approved, dict) or protected_checksum(approved) != expected_checksum:
        raise DiffValidationError("approved child specification checksum does not match the protected checksum")
    proposed = parse_root(sections)
    normalized_proposed, tracking_decision = normalize_tracking_annotation(approved, proposed)
    approved, proposed = canonical(approved), canonical(proposed)
    normalized_proposed = canonical(normalized_proposed)
    differences = compare(approved, normalized_proposed)
    evidence.write_json("approved-application.json", approved)
    evidence.write_json("proposed-application.json", proposed)
    evidence.write_json("normalization-decisions.json", [tracking_decision])
    evidence.write_json("differences.json", differences)
    evidence.complete(status, "mismatch" if differences else "approved_diff")
    if differences:
        lines = ["proposed child Application differs from the approved immutable manifest:"]
        for item in differences:
            lines.append(f"{item['path']}: {item['state']} ({item['classification']}); expected={json.dumps(item['expected'], sort_keys=True)}; proposed={json.dumps(item['proposed'], sort_keys=True)}")
        raise DiffValidationError("\n".join(lines))


def fixture(identity: tuple[str, str], operation: str, content: str = "kind: ConfigMap") -> str:
    lines = content.splitlines(); prefix = "<" if operation == "d" else ">"
    command = {"a": f"0a1,{len(lines)}", "c": "1c1", "d": f"1,{len(lines)}d0"}[operation]
    return f"\n===== {identity[0]} {identity[1]} ======\n{command}\n" + "\n".join(f"{prefix} {line}" for line in lines) + "\n"


def expect_failure(action, label: str) -> DiffValidationError:
    try: action()
    except DiffValidationError as error: return error
    raise AssertionError(f"{label} was accepted")


def self_test() -> None:
    expected = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "golden-path-api", "namespace": "gitops"}, "spec": {"project": "platform-apps", "syncPolicy": {"syncOptions": ["CreateNamespace=false"]}}}
    nested = compare({"a": {"b": [None, "", {}]}}, {"a": {"b": [None, [], {"c": 1}]}})
    assert [item["path"] for item in nested] == ["/a/b/1", "/a/b/2/c"]
    assert compare({"empty": []}, {})[0]["classification"] == "representation_difference"
    assert compare({}, {"metadata": {"uid": "x"}})[0]["classification"] == "metadata_added_by_argo"
    assert make_difference("/spec/source/helm/skipCrds", MISSING, False, "additional")["classification"] == "kubernetes_or_argo_defaulted"
    visible_digest = "sha256:" + "2" * 64
    redacted = redact_value({"digest": visible_digest, "revision": "1" * 40, "token": "private"})
    assert redacted == {"digest": visible_digest, "revision": "1" * 40, "token": "[REDACTED]"}
    protected = {"spec": {"project": "platform-apps", "source": {"targetRevision": "1" * 40, "helm": {"valuesObject": {"image": {"digest": "sha256:" + "2" * 64}}}}, "syncPolicy": {"syncOptions": ["CreateNamespace=false"]}}}
    for path, mutation in (
        ("/spec/source/helm/valuesObject/image/digest", lambda value: value["spec"]["source"]["helm"]["valuesObject"]["image"].update(digest="sha256:" + "9" * 64)),
        ("/spec/source/targetRevision", lambda value: value["spec"]["source"].update(targetRevision="9" * 40)),
        ("/spec/project", lambda value: value["spec"].update(project="other")),
        ("/spec/syncPolicy/syncOptions/0", lambda value: value["spec"]["syncPolicy"].update(syncOptions=["Other=false"])),
        ("/spec/syncPolicy/automated", lambda value: value["spec"]["syncPolicy"].update(automated={"prune": True})),
    ):
        proposed = json.loads(json.dumps(protected)); mutation(proposed)
        result = compare(protected, proposed)
        assert any(item["path"] == path and item["classification"] == "genuine_desired_specification_change" for item in result)
    with tempfile.TemporaryDirectory(prefix="argocd-diff-self-test-") as temporary:
        global EVIDENCE_ROOT
        original_root, EVIDENCE_ROOT = EVIDENCE_ROOT, pathlib.Path(temporary) / "evidence"
        approved_path = pathlib.Path(temporary) / "approved.yaml"
        approved_path.write_text(yaml.safe_dump(expected, sort_keys=False), encoding="utf-8")
        checksum = protected_checksum(expected)
        tracked = json.loads(json.dumps(expected))
        tracked.setdefault("metadata", {}).setdefault("annotations", {})[TRACKING_ANNOTATION] = required_tracking_identity()[0]
        output = fixture(ROOT_IDENTITY, "a", yaml.safe_dump(tracked, sort_keys=False).rstrip())
        validate("root", 20, output, "", approved_path, checksum, Evidence(EVIDENCE_ROOT / "1-1-1-root"))
        decision = json.loads((EVIDENCE_ROOT / "1-1-1-root/normalization-decisions.json").read_text(encoding="utf-8"))[0]
        assert decision["value"] == required_tracking_identity()[0]
        assert protected_checksum(tracked) == checksum
        changed = json.loads(json.dumps(tracked)); changed["spec"]["project"] = "other"
        error = expect_failure(lambda: validate("root", 20, fixture(ROOT_IDENTITY, "a", yaml.safe_dump(changed).rstrip()), "", approved_path, checksum, Evidence(EVIDENCE_ROOT / "2-1-1-root")), "changed project")
        assert "/spec/project" in str(error)
        operational = expect_failure(lambda: validate("root", 2, "", "authorization: Bearer private", approved_path, checksum, Evidence(EVIDENCE_ROOT / "3-1-1-root")), "operational failure")
        assert operational.exit_code == 2 and "private" not in str(operational)
        for index, altered in enumerate((
            "other:argoproj.io/Application:gitops/golden-path-api",
            "platform-environment:other/Application:gitops/golden-path-api",
            "platform-environment:argoproj.io/Other:gitops/golden-path-api",
            "platform-environment:argoproj.io/Application:other/golden-path-api",
            "platform-environment:argoproj.io/Application:gitops/other",
            "platform-environment::argoproj.io/Application:gitops/golden-path-api",
        ), start=5):
            malformed = json.loads(json.dumps(tracked)); malformed["metadata"]["annotations"][TRACKING_ANNOTATION] = altered
            expect_failure(lambda value=malformed, number=index: validate("root", 20, fixture(ROOT_IDENTITY, "a", yaml.safe_dump(value).rstrip()), "", approved_path, checksum, Evidence(EVIDENCE_ROOT / f"{number}-1-1-root")), "malformed tracking identity")
        expect_failure(lambda: normalize_tracking_annotation(expected, expected), "missing tracking annotation")
        repository_supplied = json.loads(json.dumps(expected)); repository_supplied.setdefault("metadata", {}).setdefault("annotations", {})[TRACKING_ANNOTATION] = required_tracking_identity()[0]
        expect_failure(lambda: normalize_tracking_annotation(repository_supplied, tracked), "repository-supplied tracking annotation")
        unrelated = json.loads(json.dumps(tracked)); unrelated["metadata"].setdefault("labels", {})["unexpected"] = "value"
        expect_failure(lambda: validate("root", 20, fixture(ROOT_IDENTITY, "a", yaml.safe_dump(unrelated).rstrip()), "", approved_path, checksum, Evidence(EVIDENCE_ROOT / "11-1-1-root")), "unrelated metadata")
        duplicate_yaml = yaml.safe_dump(tracked, sort_keys=False).rstrip()
        tracking_line = next(line for line in duplicate_yaml.splitlines() if TRACKING_ANNOTATION in line)
        duplicate_yaml = duplicate_yaml.replace(tracking_line, f"{tracking_line}\n{tracking_line}")
        expect_failure(lambda: parse_root(split_sections(fixture(ROOT_IDENTITY, "a", duplicate_yaml))), "multiple tracking annotations")
        expect_failure(lambda: Evidence(EVIDENCE_ROOT / "../unsafe"), "unsafe evidence traversal")
        incomplete = Evidence(EVIDENCE_ROOT / "12-1-1-root")
        incomplete.write_text("argocd-diff.txt", "safe")
        (incomplete.destination / "unexpected").mkdir()
        expect_failure(lambda: incomplete.complete(20, "approved_diff"), "incomplete or unsafe evidence")
        EVIDENCE_ROOT = original_root
    print("PASS  Argo diff diagnostics canonicalize nested state, classify every mismatch, redact secrets, and retain atomic evidence.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true"); parser.add_argument("--mode", choices=("root", "child"))
    parser.add_argument("--exit-code", type=int); parser.add_argument("--stdout", type=pathlib.Path); parser.add_argument("--stderr", type=pathlib.Path)
    parser.add_argument("--expected", type=pathlib.Path); parser.add_argument("--expected-checksum"); parser.add_argument("--evidence-dir", type=pathlib.Path)
    args = parser.parse_args()
    evidence = None
    try:
        if args.self_test: self_test(); return 0
        if None in (args.mode, args.exit_code, args.stdout, args.stderr, args.evidence_dir): raise DiffValidationError("mode, exit-code, stdout, stderr, and evidence-dir are required")
        evidence = Evidence(args.evidence_dir)
        validate(args.mode, args.exit_code, args.stdout.read_text(encoding="utf-8"), args.stderr.read_text(encoding="utf-8"), args.expected, args.expected_checksum, evidence)
        print(f"PASS  guarded {args.mode} diff contains only the approved resource changes.\nEvidence: {args.evidence_dir}"); return 0
    except (DiffValidationError, OSError, UnicodeError, json.JSONDecodeError) as error:
        if evidence is not None and not evidence.completed:
            try:
                evidence.write_json("validation-error.json", {"error": sanitize_text(str(error), 8000)})
                evidence.complete(args.exit_code if args.exit_code is not None else 1, "validation_failure")
            except (DiffValidationError, OSError) as evidence_error:
                print(f"FAIL  diagnostic evidence could not be completed atomically: {evidence_error}", file=sys.stderr)
        code = error.exit_code if isinstance(error, DiffValidationError) else 1
        print(f"FAIL  {error}", file=sys.stderr)
        if args.evidence_dir: print(f"Evidence: {args.evidence_dir}", file=sys.stderr)
        return code


if __name__ == "__main__": raise SystemExit(main())
