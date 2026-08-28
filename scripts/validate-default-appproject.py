#!/usr/bin/env python3
"""Validate the fail-closed ownership transfer for Argo CD's default project."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib

import yaml

API_VERSION = "argoproj.io/v1alpha1"
KIND = "AppProject"
NAME = "default"
NAMESPACE = "gitops"
BUILTIN_MANAGER = "argocd-server"
FIELD_MANAGER = "platform-engineering-lab-default-project"
EXPECTED_DENY_CHECKSUM = "sha256:102d3a96976670f66b262eb2c45a0ad2ff30529c79844a3dd9e85f02f1b71625"
OWNERSHIP_LABELS = {
    "app.kubernetes.io/component": "project-guard",
    "app.kubernetes.io/managed-by": "platform-engineering-lab",
    "app.kubernetes.io/part-of": "argocd",
    "platform.engineering-lab/owner": "platform-team",
}
OWNERSHIP_ANNOTATIONS = {"platform.engineering-lab/purpose": "deny-all-default-project"}
PERMISSIVE_SPEC = {
    "clusterResourceWhitelist": [{"group": "*", "kind": "*"}],
    "destinations": [{"namespace": "*", "server": "*"}],
    "sourceRepos": ["*"],
}
DENY_SPEC = {
    "description": "Deny-all default project; applications must use a dedicated project.",
    "sourceRepos": [],
    "destinations": [],
    "clusterResourceWhitelist": [],
    "namespaceResourceWhitelist": [],
}
SPEC_FIELDS = tuple(DENY_SPEC)
PERMISSION_FIELDS = ("sourceRepos", "destinations", "clusterResourceWhitelist", "namespaceResourceWhitelist")
CURRENT_OWNED_FIELDS = tuple(PERMISSIVE_SPEC)
ALLOWED_DIFF_PATHS = {
    *(f"metadata.labels.{key}" for key in OWNERSHIP_LABELS),
    *(f"metadata.annotations.{key}" for key in OWNERSHIP_ANNOTATIONS),
    *(f"spec.{key}" for key in SPEC_FIELDS),
}


def load(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) if path.suffix in {".yaml", ".yml"} else json.loads(text)


def canonical_checksum(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def protected(value: dict) -> dict:
    metadata = value.get("metadata", {})
    return {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "metadata": {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "labels": metadata.get("labels", {}),
            "annotations": metadata.get("annotations", {}),
        },
        "spec": value.get("spec", {}),
    }


def checksum(value: dict) -> str:
    return canonical_checksum(protected(value))


def identity(value: dict) -> tuple[str, str]:
    metadata = value.get("metadata", {})
    uid = metadata.get("uid")
    resource_version = metadata.get("resourceVersion")
    if not isinstance(uid, str) or not uid or not isinstance(resource_version, str) or not resource_version:
        raise ValueError("default AppProject UID and resourceVersion must be complete")
    return uid, resource_version


def validate_identity(value: dict) -> None:
    metadata = value.get("metadata", {})
    if value.get("apiVersion") != API_VERSION or value.get("kind") != KIND:
        raise ValueError("unexpected default AppProject API identity")
    if metadata.get("name") != NAME or metadata.get("namespace") != NAMESPACE:
        raise ValueError("unexpected default AppProject resource identity")


def expected_document() -> dict:
    return {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "metadata": {
            "name": NAME,
            "namespace": NAMESPACE,
            "labels": copy.deepcopy(OWNERSHIP_LABELS),
            "annotations": copy.deepcopy(OWNERSHIP_ANNOTATIONS),
        },
        "spec": copy.deepcopy(DENY_SPEC),
    }


def validate_expected(value: dict) -> None:
    if protected(value) != expected_document():
        raise ValueError("deny-all manifest differs from the protected repository contract")
    if '"*"' in json.dumps(value, sort_keys=True):
        raise ValueError("deny-all manifest contains a wildcard")
    if checksum(value) != EXPECTED_DENY_CHECKSUM:
        raise ValueError("deny-all manifest checksum differs from the approved contract")


def fields_v1_paths(fields: dict, prefix: tuple[str, ...] = ()) -> set[str]:
    paths: set[str] = set()
    if not isinstance(fields, dict):
        return paths
    for raw_key, child in fields.items():
        if not raw_key.startswith("f:"):
            continue
        path = prefix + (raw_key[2:],)
        paths.add(".".join(path))
        paths.update(fields_v1_paths(child, path))
    return paths


def managed_owners(value: dict, paths: set[str]) -> dict[str, set[str]]:
    owners = {path: set() for path in paths}
    entries = value.get("metadata", {}).get("managedFields", [])
    if not isinstance(entries, list):
        raise ValueError("managedFields is malformed")
    for entry in entries:
        manager = entry.get("manager")
        if not isinstance(manager, str) or not manager:
            raise ValueError("managedFields contains an invalid manager")
        owned = fields_v1_paths(entry.get("fieldsV1", {}))
        for path in paths:
            if path in owned:
                owners[path].add(manager)
    return owners


def require_builtin_ownership(value: dict) -> dict[str, set[str]]:
    paths = {f"spec.{field}" for field in SPEC_FIELDS}
    owners = managed_owners(value, paths)
    for path, managers in owners.items():
        expected = {BUILTIN_MANAGER} if path.removeprefix("spec.") in CURRENT_OWNED_FIELDS else set()
        if managers != expected:
            raise ValueError(f"protected field {path} has unexpected managers: {sorted(managers)}")
    return owners


def desired_paths() -> set[str]:
    return {
        *(f"metadata.labels.{key}" for key in OWNERSHIP_LABELS),
        *(f"metadata.annotations.{key}" for key in OWNERSHIP_ANNOTATIONS),
        *(f"spec.{key}" for key in SPEC_FIELDS),
    }


def require_dedicated_ownership(value: dict) -> None:
    owners = managed_owners(value, desired_paths())
    for path, managers in owners.items():
        if FIELD_MANAGER not in managers:
            raise ValueError(f"dedicated field manager does not own {path}: {sorted(managers)}")
    operations = {
        entry.get("operation")
        for entry in value.get("metadata", {}).get("managedFields", [])
        if entry.get("manager") == FIELD_MANAGER
    }
    if operations != {"Apply"}:
        raise ValueError(f"dedicated field manager operation must be Apply: {sorted(str(item) for item in operations)}")


def validate_applications(value: dict) -> None:
    if value.get("kind") != "List" or not isinstance(value.get("items"), list):
        raise ValueError("Application listing is malformed")
    references = []
    for application in value["items"]:
        project = application.get("spec", {}).get("project", "default")
        if project == "default":
            metadata = application.get("metadata", {})
            references.append(f"{metadata.get('namespace', '?')}/{metadata.get('name', '?')}")
    if references:
        raise ValueError("Applications reference the default project: " + ", ".join(sorted(references)))


def validate_live(expected: dict, live: dict) -> str:
    validate_expected(expected)
    validate_identity(live)
    if protected(live) != protected(expected):
        raise ValueError("live default AppProject differs from the deny-all ownership and specification contract")
    return checksum(live)


def diff_paths(left: object, right: object, prefix: tuple[str, ...] = ()) -> set[str]:
    if isinstance(left, dict) or isinstance(right, dict):
        left_map = left if isinstance(left, dict) else {}
        right_map = right if isinstance(right, dict) else {}
        changed: set[str] = set()
        for key in set(left_map) | set(right_map):
            changed.update(diff_paths(left_map.get(key), right_map.get(key), prefix + (str(key),)))
        return changed
    return {".".join(prefix)} if left != right else set()


def mutation_view(value: dict) -> dict:
    result = copy.deepcopy(value)
    result.pop("status", None)
    metadata = result.get("metadata", {})
    for key in ("creationTimestamp", "generation", "managedFields", "resourceVersion", "uid"):
        metadata.pop(key, None)
    return result


def confirmation(record: dict) -> str:
    return "/".join((record["context"], record["namespace"], record["name"], record["uid"],
                     record["currentChecksum"], record["desiredChecksum"]))


def validate_confirmation(record: dict, supplied: str) -> None:
    if supplied != confirmation(record):
        raise ValueError("ownership-transfer confirmation does not match the protected transaction identity")


def build_record(live: dict, desired: dict, applications: dict) -> dict:
    validate_identity(live)
    validate_expected(desired)
    validate_applications(applications)
    uid, resource_version = identity(live)
    if protected(live) == protected(desired):
        require_dedicated_ownership(live)
        state = "hardened"
        conflict_fields: list[str] = []
    else:
        if live.get("spec") != PERMISSIVE_SPEC:
            raise ValueError("current specification is not the recognized built-in permissive default")
        metadata = live.get("metadata", {})
        if metadata.get("labels", {}) or metadata.get("annotations", {}):
            raise ValueError("built-in default project has unexpected labels or annotations")
        owners = require_builtin_ownership(live)
        state = "permissive"
        conflict_fields = sorted(path for path, managers in owners.items() if managers)
    generation = live.get("metadata", {}).get("generation")
    if not isinstance(generation, int) or generation < 1:
        raise ValueError("default AppProject generation is invalid")
    return {
        "state": state,
        "context": "kind-platform-engineering-lab",
        "namespace": NAMESPACE,
        "name": NAME,
        "uid": uid,
        "resourceVersion": resource_version,
        "generation": generation,
        "currentChecksum": checksum(live),
        "desiredChecksum": checksum(desired),
        "conflictingManager": BUILTIN_MANAGER if conflict_fields else None,
        "conflictingFields": conflict_fields,
        "currentProtected": protected(live),
    }


def verify_unchanged(record: dict, live: dict, applications: dict) -> None:
    validate_identity(live)
    validate_applications(applications)
    uid, resource_version = identity(live)
    if uid != record["uid"] or resource_version != record["resourceVersion"]:
        raise ValueError("UID or resourceVersion changed during ownership-transfer preflight")
    if protected(live) != record["currentProtected"] or checksum(live) != record["currentChecksum"]:
        raise ValueError("default AppProject specification changed during ownership-transfer preflight")
    if record["state"] == "permissive":
        require_builtin_ownership(live)
    else:
        require_dedicated_ownership(live)


def validate_dry_run(record: dict, live: dict, dry_run: dict, desired: dict) -> None:
    validate_identity(dry_run)
    if dry_run.get("metadata", {}).get("uid") != record["uid"]:
        raise ValueError("dry-run changed the resource UID")
    changed = diff_paths(mutation_view(live), mutation_view(dry_run))
    unexpected = sorted(changed - ALLOWED_DIFF_PATHS)
    if unexpected:
        raise ValueError("server-side dry-run changed unexpected fields: " + ", ".join(unexpected))
    if protected(dry_run) != protected(desired):
        raise ValueError("server-side dry-run did not produce the exact deny-all contract")


def validate_post(record: dict, live: dict, desired: dict, stabilized: bool = False) -> str:
    result = validate_live(desired, live)
    uid, _ = identity(live)
    if uid != record["uid"]:
        raise ValueError("default AppProject UID changed during ownership transfer")
    expected_generation = record["generation"] + (0 if record["state"] == "hardened" else 1)
    if live.get("metadata", {}).get("generation") != expected_generation:
        raise ValueError(f"unexpected post-transfer generation; expected {expected_generation}")
    require_dedicated_ownership(live)
    if result != record["desiredChecksum"]:
        raise ValueError("post-transfer deny-all checksum mismatch")
    if stabilized and any(live.get("spec", {}).get(field) for field in PERMISSION_FIELDS):
        raise ValueError("a permission reappeared during stabilization")
    return result


def self_test() -> None:
    desired = expected_document()

    def managed(manager: str, fields: tuple[str, ...], operation: str = "Update") -> dict:
        return {"manager": manager, "operation": operation, "fieldsV1": {"f:spec": {f"f:{field}": {} for field in fields}}}

    def permissive() -> dict:
        return {
            "apiVersion": API_VERSION, "kind": KIND,
            "metadata": {"name": NAME, "namespace": NAMESPACE, "uid": "uid-1", "resourceVersion": "10",
                         "generation": 1, "managedFields": [managed(BUILTIN_MANAGER, CURRENT_OWNED_FIELDS)]},
            "spec": copy.deepcopy(PERMISSIVE_SPEC),
        }

    applications = {"kind": "List", "items": []}
    live = permissive()
    record = build_record(live, desired, applications)
    assert record["state"] == "permissive" and record["conflictingManager"] == BUILTIN_MANAGER
    expected_confirmation = "kind-platform-engineering-lab/gitops/default/uid-1/"
    assert confirmation(record).startswith(expected_confirmation)
    validate_confirmation(record, confirmation(record))
    dry = copy.deepcopy(live)
    dry["metadata"]["labels"] = copy.deepcopy(OWNERSHIP_LABELS)
    dry["metadata"]["annotations"] = copy.deepcopy(OWNERSHIP_ANNOTATIONS)
    dry["spec"] = copy.deepcopy(DENY_SPEC)
    validate_dry_run(record, live, dry, desired)
    post = copy.deepcopy(dry)
    post["metadata"].update({"resourceVersion": "11", "generation": 2})
    post["metadata"]["managedFields"] = [managed(FIELD_MANAGER, SPEC_FIELDS, "Apply")]
    post["metadata"]["managedFields"][0]["fieldsV1"].update({
        "f:metadata": {
            "f:labels": {f"f:{key}": {} for key in OWNERSHIP_LABELS},
            "f:annotations": {f"f:{key}": {} for key in OWNERSHIP_ANNOTATIONS},
        }
    })
    assert validate_post(record, post, desired) == checksum(desired)
    assert validate_post(record, post, desired, stabilized=True) == checksum(desired)
    assert build_record(post, desired, applications)["state"] == "hardened"

    def rejected(function, *arguments) -> None:
        try:
            function(*arguments)
        except ValueError:
            return
        raise AssertionError("unsafe ownership-transfer fixture was accepted")

    unexpected = permissive(); unexpected["metadata"]["managedFields"] = [managed("other", CURRENT_OWNED_FIELDS)]
    rejected(build_record, unexpected, desired, applications)
    multiple = permissive(); multiple["metadata"]["managedFields"].append(managed("other", ("sourceRepos",)))
    rejected(build_record, multiple, desired, applications)
    changed_uid = copy.deepcopy(live); changed_uid["metadata"]["uid"] = "uid-2"
    rejected(verify_unchanged, record, changed_uid, applications)
    changed_rv = copy.deepcopy(live); changed_rv["metadata"]["resourceVersion"] = "11"
    rejected(verify_unchanged, record, changed_rv, applications)
    changed_spec = copy.deepcopy(live); changed_spec["spec"]["sourceRepos"] = ["https://example.invalid/repo"]
    rejected(verify_unchanged, record, changed_spec, applications)
    referencing = {"kind": "List", "items": [{"metadata": {"namespace": "gitops", "name": "unsafe"}, "spec": {}}]}
    rejected(build_record, live, desired, referencing)
    unexpected_dry = copy.deepcopy(dry); unexpected_dry["metadata"]["finalizers"] = ["unexpected"]
    rejected(validate_dry_run, record, live, unexpected_dry, desired)
    restored = copy.deepcopy(post); restored["spec"]["sourceRepos"] = ["*"]
    rejected(validate_post, record, restored, desired, True)
    rejected(validate_confirmation, record, confirmation({**record, "uid": "wrong-uid"}))
    print("PASS  default-project adoption rejects unsafe owners, races, references, dry-run scope expansion, and permission restoration.")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    preflight = sub.add_parser("preflight")
    for name in ("desired", "live", "applications", "output"):
        preflight.add_argument(f"--{name}", type=pathlib.Path, required=True)
    unchanged = sub.add_parser("verify-unchanged")
    for name in ("record", "live", "applications"):
        unchanged.add_argument(f"--{name}", type=pathlib.Path, required=True)
    dry_run = sub.add_parser("validate-dry-run")
    for name in ("record", "live", "dry-run", "desired"):
        dry_run.add_argument(f"--{name}", type=pathlib.Path, required=True)
    post = sub.add_parser("validate-post")
    for name in ("record", "live", "desired"):
        post.add_argument(f"--{name}", type=pathlib.Path, required=True)
    post.add_argument("--stabilized", action="store_true")
    validate = sub.add_parser("validate-live")
    validate.add_argument("--live", type=pathlib.Path, required=True)
    validate.add_argument("--desired", type=pathlib.Path, required=True)
    field = sub.add_parser("field")
    field.add_argument("--record", type=pathlib.Path, required=True)
    field.add_argument("--name", required=True,
                       choices=("state", "uid", "resourceVersion", "generation", "currentChecksum", "desiredChecksum"))
    confirmation_parser = sub.add_parser("confirmation")
    confirmation_parser.add_argument("--record", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    elif args.command == "preflight":
        record = build_record(load(args.live), load(args.desired), load(args.applications))
        args.output.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: record[key] for key in ("state", "uid", "resourceVersion", "generation", "currentChecksum",
                                                        "desiredChecksum", "conflictingManager", "conflictingFields")}, indent=2))
    elif args.command == "verify-unchanged":
        verify_unchanged(load(args.record), load(args.live), load(args.applications))
        print("PASS  UID, resourceVersion, specification, references, and field ownership remain unchanged.")
    elif args.command == "validate-dry-run":
        validate_dry_run(load(args.record), load(args.live), load(getattr(args, "dry_run")), load(args.desired))
        print("PASS  forced server-side dry-run changes only the reviewed default-project fields.")
    elif args.command == "validate-post":
        print(validate_post(load(args.record), load(args.live), load(args.desired), args.stabilized))
    elif args.command == "validate-live":
        live = load(args.live)
        print(validate_live(load(args.desired), live))
        require_dedicated_ownership(live)
    elif args.command == "field":
        print(load(args.record)[args.name])
    elif args.command == "confirmation":
        print(confirmation(load(args.record)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
