#!/usr/bin/env python3
"""Classify a change for image and chart promotion decisions."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

IMAGE_INPUTS = (
    "applications/golden-path-api/Dockerfile",
    "applications/golden-path-api/.dockerignore",
    "applications/golden-path-api/src/",
    "applications/golden-path-api/requirements/runtime.in",
    "applications/golden-path-api/requirements/runtime.txt",
    "scripts/lib/supply-chain-common.sh",
    "scripts/supply-chain.sh",
)
CHART_INPUTS = ("charts/golden-path-api/",)
DESIRED_STATE_INPUTS = ("environments/local/",)


def affects_image(path: str) -> bool:
    return any(path == item or item.endswith("/") and path.startswith(item) for item in IMAGE_INPUTS)


def affects(path: str, inputs: tuple[str, ...]) -> bool:
    return any(path == item or item.endswith("/") and path.startswith(item) for item in inputs)


def classify(paths: list[str]) -> str:
    if any(affects_image(path) for path in paths):
        return "image-impacting"
    if any(affects(path, CHART_INPUTS) for path in paths):
        return "chart-impacting-only"
    if any(affects(path, DESIRED_STATE_INPUTS) for path in paths):
        return "desired-state-only"
    return "unrelated"


def changed_paths(base: str, head: str) -> list[str]:
    for revision in (base, head):
        if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            raise SystemExit(f"invalid Git revision: {revision!r}")
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def valid_revision(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def chart_matches_approved_revision(approved_revision: str, head: str) -> bool:
    if not valid_revision(approved_revision) or not valid_revision(head):
        raise SystemExit("approved chart revision and head must be complete lowercase Git SHAs")
    subprocess.run(["git", "cat-file", "-e", f"{approved_revision}^{{commit}}"], check=True)
    result = subprocess.run(
        ["git", "diff", "--quiet", approved_revision, head, "--", *CHART_INPUTS],
        check=False,
    )
    if result.returncode not in (0, 1):
        raise SystemExit("unable to compare the approved and current chart trees")
    return result.returncode == 0


def chart_promotion_required(category: str, approved_chart_matches: bool) -> bool:
    return category == "chart-impacting-only" and not approved_chart_matches


def self_test() -> None:
    cases = {
        "application source": (["applications/golden-path-api/src/golden_path_api/main.py"], "image-impacting"),
        "Dockerfile": (["applications/golden-path-api/Dockerfile"], "image-impacting"),
        "runtime lock": (["applications/golden-path-api/requirements/runtime.txt"], "image-impacting"),
        "chart only": (["charts/golden-path-api/values.yaml"], "chart-impacting-only"),
        "environment digest": (["environments/local/gitops/applications/golden-path-api.yaml"], "desired-state-only"),
        "documentation": (["docs/architecture/gitops-delivery.md"], "unrelated"),
        "mixed application and chart": (["applications/golden-path-api/src/golden_path_api/main.py", "charts/golden-path-api/values.yaml"], "image-impacting"),
    }
    for name, (paths, expected) in cases.items():
        assert classify(paths) == expected, name
    assert chart_promotion_required("chart-impacting-only", False)
    assert not chart_promotion_required("chart-impacting-only", True)
    assert not chart_promotion_required("desired-state-only", False)
    print("PASS  image, chart, desired-state, unrelated, and mixed change classification is correct.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--github-output", type=pathlib.Path)
    parser.add_argument("--evidence", type=pathlib.Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.base or not args.head:
        parser.error("--base and --head are required")
    paths = changed_paths(args.base, args.head)
    category = classify(paths)
    approved_chart_matches = False
    if category == "chart-impacting-only" and args.evidence:
        try:
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            approved_revision = evidence["chartRevision"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise SystemExit(f"unable to resolve approved chart revision: {error}") from error
        approved_chart_matches = chart_matches_approved_revision(approved_revision, args.head)
    chart_required = chart_promotion_required(category, approved_chart_matches)
    print(f"Change category: {category}")
    for path in paths:
        print(f"- {path}")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"category={category}\n")
            output.write(f"image_required={'true' if category == 'image-impacting' else 'false'}\n")
            output.write(f"chart_required={'true' if chart_required else 'false'}\n")
            output.write(f"chart_changed={'true' if any(affects(path, CHART_INPUTS) for path in paths) else 'false'}\n")


if __name__ == "__main__":
    main()
