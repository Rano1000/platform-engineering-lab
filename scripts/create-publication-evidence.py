#!/usr/bin/env python3
"""Create immutable evidence after registry publication and verification."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re

REVISION = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def file_digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--artifact-directory", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    if not args.source_run_id.isdigit() or not REVISION.fullmatch(args.source_revision):
        raise SystemExit("invalid source identity")
    if args.image != "ghcr.io/rano1000/golden-path-api" or not DIGEST.fullmatch(args.digest):
        raise SystemExit("invalid immutable registry identity")
    root = args.artifact_directory
    scan_root = root / "registry-scan"
    summary = json.loads((scan_root / "scan-summary.json").read_text(encoding="utf-8"))
    report_path = scan_root / "trivy-vulnerabilities.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    findings = [item for result in report.get("Results", []) for item in result.get("Vulnerabilities") or []]
    fixable = [item for item in findings if item.get("Severity") in {"HIGH", "CRITICAL"} and item.get("FixedVersion")]
    if fixable:
        raise SystemExit("fixable HIGH or CRITICAL vulnerability blocks evidence")
    reference = f"{args.image}@{args.digest}"
    if summary.get("image") != reference or summary.get("revision") != args.source_revision:
        raise SystemExit("registry scan identity mismatch")
    visibility = package.get("visibility", "unknown")
    evidence = {
        "schemaVersion": 1,
        "sourceRunId": args.source_run_id,
        "imageSourceRevision": args.source_revision,
        "image": args.image,
        "imageDigest": args.digest,
        "ociRevision": args.source_revision,
        "archiveSha256": file_digest(root / "golden-path-api.tar"),
        "sbomSha256": file_digest(root / "golden-path-api.cdx.json"),
        "vulnerabilityReportSha256": file_digest(root / "trivy-vulnerabilities.json"),
        "registryVulnerabilityReportSha256": file_digest(report_path),
        "attestations": {"archive": "verified", "sbom": "verified", "registryImage": "verified"},
        "vulnerabilities": {
            "severityTotals": dict(sorted(collections.Counter(item.get("Severity", "UNKNOWN") for item in findings).items())),
            "fixableHighCritical": 0,
        },
        "scanner": summary.get("scanner"),
        "database": summary.get("database"),
        "package": {
            "visibility": visibility,
            "repositoryLinked": package.get("repository", {}).get("full_name") == "Rano1000/platform-engineering-lab",
        },
        "promotionEligible": visibility == "public" and package.get("repository", {}).get("full_name") == "Rano1000/platform-engineering-lab",
    }
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
