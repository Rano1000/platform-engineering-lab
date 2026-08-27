#!/usr/bin/env python3
"""Create machine-readable promotion evidence after all external checks pass."""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re

REVISION = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def checksum(path: pathlib.Path) -> str:
    value = path.read_text(encoding="utf-8").split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SystemExit(f"invalid checksum file: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chart-revision", required=True)
    parser.add_argument("--image-source-revision", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--archive-checksum", required=True, type=pathlib.Path)
    parser.add_argument("--sbom-checksum", required=True, type=pathlib.Path)
    parser.add_argument("--vulnerability-report-checksum", required=True, type=pathlib.Path)
    parser.add_argument("--scan-summary", required=True, type=pathlib.Path)
    parser.add_argument("--scan-report", required=True, type=pathlib.Path)
    parser.add_argument("--package", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    summary = json.loads(args.scan_summary.read_text(encoding="utf-8"))
    report = json.loads(args.scan_report.read_text(encoding="utf-8"))
    package = json.loads(args.package.read_text(encoding="utf-8"))
    if not REVISION.fullmatch(args.chart_revision):
        raise SystemExit("chart revision must be a complete lowercase Git SHA")
    if not REVISION.fullmatch(args.image_source_revision):
        raise SystemExit("image source revision must be a complete lowercase Git SHA")
    if not DIGEST.fullmatch(args.image_digest):
        raise SystemExit("image digest must be complete and immutable")
    if package.get("visibility") != "public":
        raise SystemExit("GHCR package visibility is not public")
    if package.get("repository", {}).get("full_name") != "Rano1000/platform-engineering-lab":
        raise SystemExit("GHCR package is not linked to the source repository")
    findings = [
        finding
        for result in report.get("Results", [])
        for finding in result.get("Vulnerabilities") or []
    ]
    fixable_high = sum(item.get("Severity") == "HIGH" and bool(item.get("FixedVersion")) for item in findings)
    fixable_critical = sum(item.get("Severity") == "CRITICAL" and bool(item.get("FixedVersion")) for item in findings)
    severity_totals = dict(sorted(collections.Counter(item.get("Severity", "UNKNOWN") for item in findings).items()))
    expected_reference = "ghcr.io/rano1000/golden-path-api@" + args.image_digest
    if summary.get("image") != expected_reference or summary.get("revision") != args.image_source_revision:
        raise SystemExit("vulnerability evidence does not match the promoted image and source revision")
    if summary.get("findingsBySeverity") != severity_totals:
        raise SystemExit("vulnerability summary differs from the retained scan report")
    if fixable_high or fixable_critical:
        raise SystemExit("fixable HIGH or CRITICAL vulnerabilities block promotion")
    evidence = {
        "schemaVersion": 2,
        "chartRevision": args.chart_revision,
        "imageSourceRevision": args.image_source_revision,
        "image": "ghcr.io/rano1000/golden-path-api",
        "imageDigest": args.image_digest,
        "ociRevision": args.image_source_revision,
        "archiveSha256": checksum(args.archive_checksum),
        "sbomSha256": checksum(args.sbom_checksum),
        "vulnerabilityReportSha256": checksum(args.vulnerability_report_checksum),
        "attestations": {
            "repository": "Rano1000/platform-engineering-lab",
            "owner": "Rano1000",
            "archive": "verified",
            "sbom": "verified",
            "image": "verified",
            "subjects": {
                "archive": "sha256:" + checksum(args.archive_checksum),
                "sbom": "sha256:" + checksum(args.sbom_checksum),
                "image": args.image_digest,
            },
        },
        "vulnerabilities": {
            "severityTotals": severity_totals,
            "fixableHigh": fixable_high,
            "fixableCritical": fixable_critical,
        },
        "scanner": {
            "name": "Trivy",
            "version": summary.get("scanner", {}).get("version"),
            "databaseUpdatedAt": summary.get("database", {}).get("UpdatedAt"),
        },
        "publication": {"visibility": "public", "repositoryLinked": True},
    }
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
