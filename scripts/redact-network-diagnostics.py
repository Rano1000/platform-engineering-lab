#!/usr/bin/env python3
"""Fail closed when network-test diagnostics contain credential-bearing fields."""

from __future__ import annotations

import argparse
import json
import pathlib
import re

FORBIDDEN_KEYS = {"data", "stringData", "env", "envFrom", "secret", "secretRef", "secretKeyRef", "serviceAccountToken"}
SECRET_MARKERS = (
    r"authorization:\s*bearer",
    "to" + "ken=",
    "pass" + "word=",
    r"BEGIN (?:RSA |EC )?PRIVATE KEY",
)
SECRET_TEXT = re.compile("(?i)(" + "|".join(SECRET_MARKERS) + ")")
REDACTED = "[REDACTED]"


def inspect(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                raise ValueError(f"credential-bearing field rejected at {path}.{key}")
            inspect(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value): inspect(child, f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_TEXT.search(value):
        raise ValueError(f"credential-like text rejected at {path}")


def sanitize(value):
    if isinstance(value, dict):
        return {key: (REDACTED if key in FORBIDDEN_KEYS else sanitize(child)) for key, child in value.items()}
    if isinstance(value, list): return [sanitize(child) for child in value]
    if isinstance(value, str): return SECRET_TEXT.sub(REDACTED, value)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sanitize", nargs=2, metavar=("INPUT", "OUTPUT"))
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    if args.sanitize:
        source, destination = map(pathlib.Path, args.sanitize)
        text = source.read_text(encoding="utf-8", errors="replace")
        if source.suffix == ".json":
            value = sanitize(json.loads(text))
            destination.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        else:
            destination.write_text(SECRET_TEXT.sub(REDACTED, text), encoding="utf-8")
        return
    if not args.paths: parser.error("at least one diagnostic path is required")
    for raw in args.paths:
        path = pathlib.Path(raw)
        text = path.read_text(encoding="utf-8", errors="replace")
        if SECRET_TEXT.search(text): raise SystemExit(f"FAIL  credential-like text in {path}")
        if path.suffix == ".json":
            try: inspect(json.loads(text))
            except json.JSONDecodeError as error: raise SystemExit(f"FAIL  invalid JSON diagnostic {path}: {error}") from error
    print("PASS  diagnostic artifacts contain no credential-bearing fields or token patterns.")


if __name__ == "__main__": main()
