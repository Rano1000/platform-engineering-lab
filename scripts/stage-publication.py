#!/usr/bin/env python3
"""Create and validate the allowlisted publication handoff artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import stat
import tempfile

SOURCE_FILES = {
    "golden-path-api.tar",
    "golden-path-api.tar.sha256",
    "golden-path-api.cdx.json",
    "golden-path-api.cdx.json.sha256",
    "sbom-metadata.json",
    "scan-summary.json",
    "trivy-metadata.json",
    "trivy-vulnerabilities.json",
    "trivy-vulnerabilities.json.sha256",
}
SCAN_FILES = {
    "scan-summary.json",
    "trivy-ignore.txt",
    "trivy-metadata.json",
    "trivy-vulnerabilities.json",
    "trivy-vulnerabilities.json.sha256",
}
VERIFICATION_FILES = {
    ".attestations-verified",
    "archive-attestation-verification.json",
    "sbom-attestation-verification.json",
    "source-run-verification.json",
}
STAGED_NAMES = {
    **{name: name for name in SOURCE_FILES},
    **{
        "scan-summary.json": "prepublication-scan-summary.json",
        "trivy-metadata.json": "prepublication-trivy-metadata.json",
        "trivy-vulnerabilities.json": "prepublication-trivy-vulnerabilities.json",
        "trivy-vulnerabilities.json.sha256": "prepublication-trivy-vulnerabilities.json.sha256",
    },
}


def digest(path: pathlib.Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def regular_file(path: pathlib.Path) -> None:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise ValueError(f"approved input is not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise ValueError(f"approved input is unreadable: {path}")


def exact_directory(path: pathlib.Path, expected: set[str]) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"input is not a real directory: {path}")
    found = {entry.name for entry in path.iterdir()}
    if found != expected:
        missing = sorted(expected - found)
        unexpected = sorted(found - expected)
        raise ValueError(f"staging input mismatch for {path}: missing={missing}, unexpected={unexpected}")
    for name in expected:
        regular_file(path / name)


def checksum_matches(directory: pathlib.Path, filename: str) -> None:
    checksum_path = directory / f"{filename}.sha256"
    fields = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or fields[1].lstrip("*") != filename or fields[0] != digest(directory / filename):
        raise ValueError(f"checksum does not match approved file: {filename}")


def stage(source: pathlib.Path, scan: pathlib.Path, verification: pathlib.Path, destination: pathlib.Path) -> None:
    exact_directory(source, SOURCE_FILES)
    exact_directory(scan, SCAN_FILES)
    exact_directory(verification, VERIFICATION_FILES)
    for directory, filename in (
        (source, "golden-path-api.tar"),
        (source, "golden-path-api.cdx.json"),
        (source, "trivy-vulnerabilities.json"),
        (scan, "trivy-vulnerabilities.json"),
    ):
        checksum_matches(directory, filename)
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError(f"staging destination is not a real directory: {destination}")
        if any(destination.iterdir()):
            raise ValueError(f"staging destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    copies = [(source / name, destination / name) for name in sorted(SOURCE_FILES)]
    copies.extend(
        (scan / name, destination / STAGED_NAMES[name])
        for name in sorted(SCAN_FILES - {"trivy-ignore.txt"})
    )
    copies.extend((verification / name, destination / name) for name in sorted(VERIFICATION_FILES))
    for origin, target in copies:
        shutil.copyfile(origin, target)
        regular_file(target)
    manifest = {
        "schemaVersion": 1,
        "files": [
            {"name": path.name, "sha256": digest(path), "size": path.stat().st_size}
            for path in sorted(destination.iterdir())
        ],
    }
    (destination / "staging-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate(destination)


def validate(destination: pathlib.Path) -> None:
    expected = set(SOURCE_FILES) | set(VERIFICATION_FILES) | {
        "prepublication-scan-summary.json",
        "prepublication-trivy-metadata.json",
        "prepublication-trivy-vulnerabilities.json",
        "prepublication-trivy-vulnerabilities.json.sha256",
        "staging-manifest.json",
    }
    exact_directory(destination, expected)
    manifest = json.loads((destination / "staging-manifest.json").read_text(encoding="utf-8"))
    recorded = {item["name"]: item for item in manifest.get("files", [])}
    if set(recorded) != expected - {"staging-manifest.json"}:
        raise ValueError("staging manifest does not contain the exact approved file set")
    for name, item in recorded.items():
        path = destination / name
        if item != {"name": name, "sha256": digest(path), "size": path.stat().st_size}:
            raise ValueError(f"staging manifest identity mismatch: {name}")


def fixture(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    source, scan, verification = (root / name for name in ("source", "scan", "verification"))
    for directory in (source, scan, verification):
        directory.mkdir()
    for name in SOURCE_FILES:
        (source / name).write_text("evidence\n", encoding="utf-8")
    for name in SCAN_FILES:
        (scan / name).write_text("scan\n", encoding="utf-8")
    for name in VERIFICATION_FILES:
        (verification / name).write_text("verified\n", encoding="utf-8")
    for directory, filename in (
        (source, "golden-path-api.tar"),
        (source, "golden-path-api.cdx.json"),
        (source, "trivy-vulnerabilities.json"),
        (scan, "trivy-vulnerabilities.json"),
    ):
        (directory / f"{filename}.sha256").write_text(
            f"{digest(directory / filename)}  {filename}\n", encoding="utf-8"
        )
    return source, scan, verification


def self_test() -> None:
    mutations = {
        "fanal directory": lambda source, scan, verification: (scan / "fanal").mkdir(),
        "unexpected file": lambda source, scan, verification: (source / "unexpected").write_text("x"),
        "symbolic link": lambda source, scan, verification: (
            (source / "golden-path-api.tar").unlink(),
            (source / "golden-path-api.tar").symlink_to("golden-path-api.cdx.json"),
        ),
        "missing evidence": lambda source, scan, verification: (verification / "source-run-verification.json").unlink(),
        "FIFO": lambda source, scan, verification: (
            (scan / "trivy-ignore.txt").unlink(),
            os.mkfifo(scan / "trivy-ignore.txt"),
        ),
    }
    with tempfile.TemporaryDirectory() as name:
        root = pathlib.Path(name)
        source, scan, verification = fixture(root)
        stage(source, scan, verification, root / "staged")
        if any("cache" in path.name or "fanal" in path.name for path in (root / "staged").iterdir()):
            raise AssertionError("scanner cache entered staging")
    for label, mutate in mutations.items():
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            source, scan, verification = fixture(root)
            mutate(source, scan, verification)
            try:
                stage(source, scan, verification, root / "staged")
            except (OSError, ValueError):
                continue
            raise AssertionError(f"staging accepted {label}")
    print("PASS  publication staging excludes scanner cache and fanal state.")
    print("PASS  publication staging rejects unexpected, missing, symlink, and non-regular inputs.")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    for name in ("source", "scan", "verification", "destination"):
        create.add_argument(f"--{name}", required=True, type=pathlib.Path)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--directory", required=True, type=pathlib.Path)
    subparsers.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "create":
            stage(args.source, args.scan, args.verification, args.destination)
        elif args.command == "validate":
            validate(args.directory)
        else:
            self_test()
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
