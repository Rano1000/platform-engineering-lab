#!/usr/bin/env python3
"""Update only chart identity in an approved child Application and evidence."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import tempfile

REVISION = re.compile(r"^[0-9a-f]{40}$")
PRESERVED_FIELDS = (
    "imageSourceRevision",
    "imageDigest",
    "ociRevision",
    "archiveSha256",
    "sbomSha256",
    "vulnerabilityReportSha256",
    "attestations",
    "vulnerabilities",
    "scanner",
    "publication",
)


def update(application_path: pathlib.Path, evidence_path: pathlib.Path, revision: str) -> None:
    if not REVISION.fullmatch(revision):
        raise ValueError("chart revision must be a complete lowercase Git SHA")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    old = evidence.get("chartRevision")
    if not isinstance(old, str) or not REVISION.fullmatch(old) or old == revision:
        raise ValueError("current chart revision is invalid or unchanged")
    preserved = {key: evidence[key] for key in PRESERVED_FIELDS}
    application = application_path.read_text(encoding="utf-8")
    patterns = (
        (rf'(platform\.engineering-lab/chart-revision:\s+"){old}("$)', rf'\g<1>{revision}\g<2>'),
        (rf'(targetRevision:\s+"){old}("$)', rf'\g<1>{revision}\g<2>'),
    )
    for pattern, replacement in patterns:
        application, count = re.subn(pattern, replacement, application, count=1, flags=re.MULTILINE)
        if count != 1:
            raise ValueError("expected chart revision field was not updated exactly once")
    evidence["chartRevision"] = revision
    if any(evidence[key] != value for key, value in preserved.items()):
        raise ValueError("chart promotion changed immutable image or security evidence")
    application_path.write_text(application, encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        application = root / "application.yaml"
        evidence_path = root / "evidence.json"
        old, new = "a" * 40, "b" * 40
        application.write_text(
            f'annotations:\n  platform.engineering-lab/chart-revision: "{old}"\nsource:\n  targetRevision: "{old}"\n',
            encoding="utf-8",
        )
        evidence = {"chartRevision": old, **{key: {"retained": True} for key in PRESERVED_FIELDS}}
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        update(application, evidence_path, new)
        result = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert result["chartRevision"] == new
        assert all(result[key] == evidence[key] for key in PRESERVED_FIELDS)
        assert application.read_text(encoding="utf-8").count(new) == 2
        for invalid in (new, "main"):
            try:
                update(application, evidence_path, invalid)
            except ValueError:
                continue
            raise AssertionError(f"chart update accepted invalid or stale revision {invalid}")
    print("PASS  chart promotion updates only chart identity and preserves image and security evidence.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--application", type=pathlib.Path)
    parser.add_argument("--evidence", type=pathlib.Path)
    parser.add_argument("--chart-revision")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.application or not args.evidence or not args.chart_revision:
        parser.error("provide --application, --evidence, and --chart-revision")
    try:
        update(args.application, args.evidence, args.chart_revision)
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR {error}") from error


if __name__ == "__main__":
    main()
