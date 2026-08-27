#!/usr/bin/env python3
"""Validate immutable image promotion evidence and desired state."""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re
import sys

import yaml

REPOSITORY = "Rano1000/platform-engineering-lab"
OWNER = "Rano1000"
IMAGE = "ghcr.io/rano1000/golden-path-api"
SOURCE_REPOSITORY = "https://github.com/Rano1000/platform-engineering-lab.git"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_evidence(evidence: dict) -> None:
    required = {
        "schemaVersion",
        "chartRevision",
        "imageSourceRevision",
        "image",
        "imageDigest",
        "ociRevision",
        "archiveSha256",
        "sbomSha256",
        "vulnerabilityReportSha256",
        "attestations",
        "vulnerabilities",
        "scanner",
        "publication",
    }
    require(set(evidence) == required, "promotion evidence has missing or unexpected fields")
    require(evidence["schemaVersion"] == 2, "unsupported evidence schema")
    require(bool(REVISION.fullmatch(evidence["chartRevision"])), "invalid chart revision")
    require(bool(REVISION.fullmatch(evidence["imageSourceRevision"])), "invalid image source revision")
    require(evidence["ociRevision"] == evidence["imageSourceRevision"], "OCI and image source revisions differ")
    require(evidence["image"] == IMAGE, "unexpected image owner or repository")
    require(bool(DIGEST.fullmatch(evidence["imageDigest"])), "mutable or incomplete image digest")
    for name in ("archiveSha256", "sbomSha256", "vulnerabilityReportSha256"):
        require(bool(re.fullmatch(r"[0-9a-f]{64}", evidence[name])), f"invalid {name}")
    attestations = evidence["attestations"]
    require(attestations.get("repository") == REPOSITORY, "attestation repository mismatch")
    require(attestations.get("owner") == OWNER, "attestation owner mismatch")
    require(attestations.get("archive") == "verified", "archive attestation is not verified")
    require(attestations.get("sbom") == "verified", "SBOM attestation is not verified")
    require(attestations.get("image") == "verified", "image attestation is not verified")
    subjects = attestations.get("subjects", {})
    require(subjects.get("archive") == f"sha256:{evidence['archiveSha256']}", "archive subject mismatch")
    require(subjects.get("sbom") == f"sha256:{evidence['sbomSha256']}", "SBOM subject mismatch")
    require(subjects.get("image") == evidence["imageDigest"], "image subject mismatch")
    vulnerabilities = evidence["vulnerabilities"]
    require(vulnerabilities.get("fixableHigh") == 0, "fixable HIGH vulnerabilities block promotion")
    require(vulnerabilities.get("fixableCritical") == 0, "fixable CRITICAL vulnerabilities block promotion")
    require(isinstance(vulnerabilities.get("severityTotals"), dict), "severity totals are missing")
    require(evidence["scanner"].get("name") == "Trivy", "unexpected scanner")
    require(evidence["scanner"].get("version"), "scanner version is missing")
    require(evidence["scanner"].get("databaseUpdatedAt"), "scanner database timestamp is missing")
    publication = evidence["publication"]
    require(publication.get("visibility") == "public", "GHCR package is not confirmed public")
    require(publication.get("repositoryLinked") is True, "GHCR package is not linked to the source repository")


def validate_application(application: dict, evidence: dict) -> None:
    require(application.get("kind") == "Application", "desired state is not an Argo Application")
    metadata = application.get("metadata", {})
    require(metadata.get("name") == "golden-path-api" and metadata.get("namespace") == "gitops", "unexpected Application identity")
    spec = application.get("spec", {})
    require(spec.get("project") == "platform-apps", "unexpected AppProject")
    source = spec.get("source", {})
    require(source.get("repoURL") == SOURCE_REPOSITORY, "unexpected source repository")
    require(source.get("targetRevision") == evidence["chartRevision"], "desired chart revision does not match evidence")
    require(source.get("path") == "charts/golden-path-api", "unexpected chart path")
    destination = spec.get("destination", {})
    require(destination == {"server": "https://kubernetes.default.svc", "namespace": "platform-apps"}, "unexpected destination")
    require("automated" not in spec.get("syncPolicy", {}), "automated synchronization is forbidden")
    values = source.get("helm", {}).get("valuesObject", {}).get("image", {})
    require(values.get("repository") == IMAGE, "desired image repository mismatch")
    require(values.get("digest") == evidence["imageDigest"], "desired digest does not match evidence")
    require(values.get("revision") == evidence["imageSourceRevision"], "desired image revision does not match evidence")
    require(values.get("tag") == "", "mutable image tag is forbidden")
    require(values.get("pullPolicy") == "IfNotPresent", "GitOps pull policy must be IfNotPresent")
    annotations = metadata.get("annotations", {})
    require(annotations.get("platform.engineering-lab/chart-revision") == evidence["chartRevision"], "chart annotation mismatch")
    require(annotations.get("platform.engineering-lab/image-source-revision") == evidence["imageSourceRevision"], "image-source annotation mismatch")
    require(annotations.get("platform.engineering-lab/image-digest") == evidence["imageDigest"], "digest annotation mismatch")


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_files(evidence_path: pathlib.Path, application_path: pathlib.Path) -> None:
    evidence = load_json(evidence_path)
    validate_evidence(evidence)
    application = yaml.safe_load(application_path.read_text(encoding="utf-8"))
    validate_application(application, evidence)


def self_test() -> None:
    digest = "sha256:" + "a" * 64
    evidence = {
        "schemaVersion": 2,
        "chartRevision": "e" * 40,
        "imageSourceRevision": "b" * 40,
        "image": IMAGE,
        "imageDigest": digest,
        "ociRevision": "b" * 40,
        "archiveSha256": "c" * 64,
        "sbomSha256": "d" * 64,
        "vulnerabilityReportSha256": "f" * 64,
        "attestations": {
            "repository": REPOSITORY,
            "owner": OWNER,
            "archive": "verified",
            "sbom": "verified",
            "image": "verified",
            "subjects": {"archive": "sha256:" + "c" * 64, "sbom": "sha256:" + "d" * 64, "image": digest},
        },
        "vulnerabilities": {"severityTotals": {"CRITICAL": 5, "HIGH": 31}, "fixableHigh": 0, "fixableCritical": 0},
        "scanner": {"name": "Trivy", "version": "0.74.0", "databaseUpdatedAt": "2026-08-27T00:00:00Z"},
        "publication": {"visibility": "public", "repositoryLinked": True},
    }
    validate_evidence(evidence)
    application = {
        "kind": "Application",
        "metadata": {
            "name": "golden-path-api",
            "namespace": "gitops",
            "annotations": {
                "platform.engineering-lab/chart-revision": evidence["chartRevision"],
                "platform.engineering-lab/image-source-revision": evidence["imageSourceRevision"],
                "platform.engineering-lab/image-digest": digest,
            },
        },
        "spec": {
            "project": "platform-apps",
            "source": {
                "repoURL": SOURCE_REPOSITORY,
                "targetRevision": evidence["chartRevision"],
                "path": "charts/golden-path-api",
                "helm": {"valuesObject": {"image": {
                    "repository": IMAGE, "digest": digest, "revision": evidence["imageSourceRevision"],
                    "tag": "", "pullPolicy": "IfNotPresent",
                }}},
            },
            "destination": {"server": "https://kubernetes.default.svc", "namespace": "platform-apps"},
            "syncPolicy": {"syncOptions": ["CreateNamespace=false"]},
        },
    }
    validate_application(application, evidence)
    mutations = (
        ("wrong repository", lambda item: item["attestations"].update(repository="someone/else")),
        ("wrong owner", lambda item: item["attestations"].update(owner="SomeoneElse")),
        ("wrong subject", lambda item: item["attestations"]["subjects"].update(image="sha256:" + "e" * 64)),
        ("missing attestation", lambda item: item["attestations"].update(image="missing")),
        ("mutable tag", lambda item: item.update(imageDigest="latest")),
        ("fixable HIGH", lambda item: item["vulnerabilities"].update(fixableHigh=1)),
        ("fixable CRITICAL", lambda item: item["vulnerabilities"].update(fixableCritical=1)),
    )
    for name, mutation in mutations:
        candidate = copy.deepcopy(evidence)
        mutation(candidate)
        try:
            validate_evidence(candidate)
        except ValueError:
            continue
        raise AssertionError(f"policy accepted {name}")
    stale = copy.deepcopy(application)
    stale["spec"]["source"]["targetRevision"] = "a" * 40
    try:
        validate_application(stale, evidence)
    except ValueError:
        pass
    else:
        raise AssertionError("policy accepted a stale chart revision")
    mismatched_image = copy.deepcopy(application)
    mismatched_image["spec"]["source"]["helm"]["valuesObject"]["image"]["revision"] = "a" * 40
    try:
        validate_application(mismatched_image, evidence)
    except ValueError:
        pass
    else:
        raise AssertionError("policy accepted an image digest and image-source mismatch")
    chart_only_evidence = copy.deepcopy(evidence)
    chart_only_application = copy.deepcopy(application)
    preserved = {
        key: chart_only_evidence[key]
        for key in ("imageSourceRevision", "imageDigest", "ociRevision", "archiveSha256", "sbomSha256", "vulnerabilityReportSha256")
    }
    chart_only_evidence["chartRevision"] = "9" * 40
    chart_only_application["spec"]["source"]["targetRevision"] = "9" * 40
    chart_only_application["metadata"]["annotations"]["platform.engineering-lab/chart-revision"] = "9" * 40
    validate_application(chart_only_application, chart_only_evidence)
    assert all(chart_only_evidence[key] == value for key, value in preserved.items())
    print("PASS  promotion policy rejects identity, subject, attestation, mutability, stale chart, and image-source failures.")
    print("PASS  chart-only promotion changes chartRevision while preserving immutable image and scan evidence.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--evidence", type=pathlib.Path)
    parser.add_argument("--application", type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.evidence and args.application:
            validate_files(args.evidence, args.application)
            print("PASS  desired-state digest matches verified promotion evidence.")
        else:
            parser.error("use --self-test or provide --evidence and --application")
    except (ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
