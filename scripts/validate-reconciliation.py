#!/usr/bin/env python3
"""Validate immutable root reconciliation and exact child Application state."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
REVISION = re.compile(r"^[0-9a-f]{40}$")


def promotion_module():
    path = ROOT / "scripts/validate-promotion.py"
    specification = importlib.util.spec_from_file_location("validate_promotion", path)
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load promotion validator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_revision_state(environment: str, local: str, origin: str, ancestor: bool = True) -> None:
    require(bool(REVISION.fullmatch(environment)), "environmentRevision must be a complete immutable Git SHA")
    require(bool(REVISION.fullmatch(local)) and bool(REVISION.fullmatch(origin)), "local and origin revisions must be complete Git SHAs")
    require(local == environment, "local main differs from environmentRevision")
    require(origin == environment, "origin/main changed after environmentRevision was resolved")
    require(ancestor, "environmentRevision is not an ancestor of origin/main")


def load(path: pathlib.Path) -> dict:
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(content)
    document = yaml.safe_load(content)
    require(isinstance(document, dict), f"{path} is not an object")
    return document


def spec_checksum(application: dict) -> str:
    encoded = json.dumps(application["spec"], sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_approved(application: dict, evidence: dict) -> str:
    promotion = promotion_module()
    promotion.validate_evidence(evidence)
    promotion.validate_application(application, evidence)
    metadata = application.get("metadata", {})
    require("finalizers" not in metadata or not metadata["finalizers"], "child Application must not have a finalizer")
    sync_policy = application["spec"].get("syncPolicy", {})
    require("automated" not in sync_policy, "child automated synchronization is forbidden")
    require("prune" not in sync_policy and "selfHeal" not in sync_policy, "child pruning and self-healing are forbidden")
    return spec_checksum(application)


def validate_live(approved: dict, evidence: dict, live: dict, expected_checksum: str) -> None:
    approved_checksum = validate_approved(approved, evidence)
    require(approved_checksum == expected_checksum, "approved child specification checksum changed")
    promotion = promotion_module()
    promotion.validate_application(live, evidence)
    metadata = live.get("metadata", {})
    require(metadata.get("name") == "golden-path-api" and metadata.get("namespace") == "gitops", "live child identity differs")
    require("finalizers" not in metadata or not metadata["finalizers"], "live child has a cascading-deletion finalizer")
    require(live.get("spec") == approved.get("spec"), "live child Application specification differs from the approved specification")
    require(spec_checksum(live) == expected_checksum, "live child specification checksum differs")


def fixture() -> tuple[dict, dict]:
    digest = "sha256:" + "a" * 64
    chart, image = "b" * 40, "c" * 40
    evidence = {
        "schemaVersion": 2, "chartRevision": chart, "imageSourceRevision": image,
        "image": "ghcr.io/rano1000/golden-path-api", "imageDigest": digest, "ociRevision": image,
        "archiveSha256": "d" * 64, "sbomSha256": "e" * 64, "vulnerabilityReportSha256": "f" * 64,
        "attestations": {
            "repository": "Rano1000/platform-engineering-lab", "owner": "Rano1000",
            "archive": "verified", "sbom": "verified", "image": "verified",
            "subjects": {"archive": "sha256:" + "d" * 64, "sbom": "sha256:" + "e" * 64, "image": digest},
        },
        "vulnerabilities": {"severityTotals": {"HIGH": 31, "CRITICAL": 5}, "fixableHigh": 0, "fixableCritical": 0},
        "scanner": {"name": "Trivy", "version": "0.74.0", "databaseUpdatedAt": "2026-08-27T00:00:00Z"},
        "publication": {"visibility": "public", "repositoryLinked": True},
    }
    template = (ROOT / "environments/local/gitops/applications/golden-path-api.yaml.tmpl").read_text(encoding="utf-8")
    rendered = template.replace("${CHART_REVISION}", chart).replace("${IMAGE_SOURCE_REVISION}", image).replace("${IMAGE_DIGEST}", digest)
    return yaml.safe_load(rendered), evidence


def expect_failure(function, *arguments) -> None:
    try:
        function(*arguments)
    except ValueError:
        return
    raise AssertionError("invalid reconciliation state was accepted")


def self_test() -> None:
    revision = "1" * 40
    validate_revision_state(revision, revision, revision)
    expect_failure(validate_revision_state, revision, revision, "2" * 40)
    expect_failure(validate_revision_state, revision, "2" * 40, revision)
    expect_failure(validate_revision_state, revision[:12], revision[:12], revision[:12])
    expect_failure(validate_revision_state, "main", "main", "main")
    expect_failure(validate_revision_state, revision, revision, revision, False)
    approved, evidence = fixture()
    checksum = validate_approved(approved, evidence)
    validate_live(approved, evidence, copy.deepcopy(approved), checksum)
    stale_evidence = copy.deepcopy(evidence)
    stale_evidence["chartRevision"] = "9" * 40
    expect_failure(validate_approved, approved, stale_evidence)
    mutations = (
        lambda item: item["metadata"].update(name="other"),
        lambda item: item["metadata"].update(namespace="other"),
        lambda item: item["metadata"].update(finalizers=["resources-finalizer.argocd.argoproj.io"]),
        lambda item: item["spec"].update(project="other"),
        lambda item: item["spec"]["source"].update(repoURL="https://example.invalid/repo.git"),
        lambda item: item["spec"]["source"].update(path="charts/other"),
        lambda item: item["spec"]["source"].update(targetRevision="9" * 40),
        lambda item: item["spec"].update(destination={"server": "other", "namespace": "other"}),
        lambda item: item["spec"]["source"]["helm"]["valuesObject"]["image"].update(repository="other"),
        lambda item: item["spec"]["source"]["helm"]["valuesObject"]["image"].update(digest="sha256:" + "9" * 64),
        lambda item: item["spec"]["source"]["helm"]["valuesObject"]["image"].update(revision="9" * 40),
        lambda item: item["spec"].update(syncPolicy={"automated": {"prune": True}}),
    )
    for mutation in mutations:
        live = copy.deepcopy(approved)
        mutation(live)
        expect_failure(validate_live, approved, evidence, live, checksum)
    print("PASS  reconciliation rejects origin races, local divergence, mutable or invalid revisions, stale evidence, and protected live-child drift.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--application", type=pathlib.Path)
    parser.add_argument("--evidence", type=pathlib.Path)
    parser.add_argument("--live", type=pathlib.Path)
    parser.add_argument("--expected-checksum")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return
        if not args.application or not args.evidence:
            parser.error("provide --application and --evidence")
        approved, evidence = load(args.application), load(args.evidence)
        checksum = validate_approved(approved, evidence)
        if args.live:
            require(bool(args.expected_checksum), "--expected-checksum is required with --live")
            validate_live(approved, evidence, load(args.live), args.expected_checksum)
            print(f"PASS  live child Application matches approved specification sha256:{checksum}.")
        else:
            print(checksum)
    except (ValueError, KeyError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
