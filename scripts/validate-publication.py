#!/usr/bin/env python3
"""Validate source-run and artifact identities for manual GHCR publication."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import tarfile
import tempfile

REPOSITORY = "Rano1000/platform-engineering-lab"
WORKFLOW = "Application supply chain"
WORKFLOW_PATH = ".github/workflows/application-ci.yml"
REVISION = re.compile(r"^[0-9a-f]{40}$")
CHECKSUM = re.compile(r"^[0-9a-f]{64}$")
RUN_URI = re.compile(r"/actions/runs/([0-9]+)/attempts/[0-9]+$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: pathlib.Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_source(run: dict, jobs: dict, artifacts: dict, log: str, args: argparse.Namespace) -> None:
    require(str(run.get("id")) == args.run_id, "source run ID mismatch")
    require(run.get("repository", {}).get("full_name") == REPOSITORY, "source run belongs to another repository")
    require(run.get("name") == WORKFLOW and run.get("path") == WORKFLOW_PATH, "unexpected source workflow")
    require(run.get("event") == "workflow_dispatch", "source run was not manually dispatched")
    require(run.get("conclusion") == "success", "source run did not succeed")
    require(REVISION.fullmatch(args.revision) is not None, "source revision must be a complete SHA")
    require(run.get("head_sha") == args.revision, "source run revision mismatch")
    require("FORCE_IMAGE_BUILD: true" in log, "source run did not record force_image_build=true")
    conclusions = {job["name"]: job.get("conclusion") for job in jobs.get("jobs", [])}
    for name in ("Test and build once", "SBOM and vulnerability policy", "Attest image archive and SBOM"):
        require(conclusions.get(name) == "success", f"required source job did not succeed: {name}")
    expected = {
        f"golden-path-image-{args.revision}",
        f"golden-path-supply-chain-{args.revision}",
    }
    found = set()
    now = dt.datetime.now(dt.timezone.utc)
    for artifact in artifacts.get("artifacts", []):
        if artifact.get("name") not in expected:
            continue
        require(not artifact.get("expired"), f"artifact is expired: {artifact.get('name')}")
        expiry = dt.datetime.fromisoformat(artifact["expires_at"].replace("Z", "+00:00"))
        require(expiry > now, f"artifact retention elapsed: {artifact.get('name')}")
        found.add(artifact["name"])
    require(found == expected, "expected source-run artifacts are missing")


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_artifacts(directory: pathlib.Path, args: argparse.Namespace) -> None:
    archive = directory / "golden-path-api.tar"
    sbom = directory / "golden-path-api.cdx.json"
    report = directory / "trivy-vulnerabilities.json"
    require(digest(archive) == args.archive_sha256, "archive checksum mismatch")
    require(digest(sbom) == args.sbom_sha256, "SBOM checksum mismatch")
    require(digest(report) == args.vulnerability_report_sha256, "vulnerability report checksum mismatch")
    with tarfile.open(archive) as bundle:
        manifest = json.load(bundle.extractfile("manifest.json"))
        require(len(manifest) == 1, "archive must contain exactly one image")
        config = json.load(bundle.extractfile(manifest[0]["Config"]))["config"]
    expected_tag = f"golden-path-api:0.1.0-{args.revision[:12]}"
    require(manifest[0].get("RepoTags") == [expected_tag], "archive tag does not match source revision")
    require(config.get("Labels", {}).get("org.opencontainers.image.revision") == args.revision, "OCI revision mismatch")
    require(not any(tag.endswith(":latest") for tag in manifest[0]["RepoTags"]), "latest tag is forbidden")
    document = json.loads(sbom.read_text(encoding="utf-8"))
    require(document.get("bomFormat") == "CycloneDX" and document.get("components"), "invalid CycloneDX SBOM")
    require(isinstance(json.loads(report.read_text(encoding="utf-8")).get("Results"), list), "invalid vulnerability report")


def validate_attestation(path: pathlib.Path, subject: str, checksum: str, revision: str, run_id: str) -> None:
    results = load(path)
    require(isinstance(results, list) and results, "attestation verification result is empty")
    result = results[0]["verificationResult"]
    signature = result["signature"]["certificate"]
    require(signature.get("githubWorkflowRepository") == REPOSITORY, "attestation repository mismatch")
    require(signature.get("githubWorkflowName") == WORKFLOW, "attestation workflow mismatch")
    require(signature.get("githubWorkflowTrigger") == "workflow_dispatch", "attestation trigger mismatch")
    require(signature.get("sourceRepositoryDigest") == revision, "attestation source revision mismatch")
    match = RUN_URI.search(signature.get("runInvocationURI", ""))
    require(bool(match) and match.group(1) == run_id, "attestation run identity mismatch")
    subjects = result["statement"].get("subject", [])
    require(any(item.get("name") == subject and item.get("digest", {}).get("sha256") == checksum for item in subjects),
            "attestation subject mismatch")


def self_test() -> None:
    revision = "a" * 40
    now = dt.datetime.now(dt.timezone.utc)
    run = {"id": 123, "repository": {"full_name": REPOSITORY}, "name": WORKFLOW, "path": WORKFLOW_PATH,
           "event": "workflow_dispatch", "conclusion": "success", "head_sha": revision}
    jobs = {"jobs": [{"name": name, "conclusion": "success"} for name in
                     ("Test and build once", "SBOM and vulnerability policy", "Attest image archive and SBOM")]}
    artifacts = {"artifacts": [{"name": f"golden-path-{kind}-{revision}", "expired": False,
                                 "expires_at": (now + dt.timedelta(days=1)).isoformat()} for kind in
                                ("image", "supply-chain")]}
    args = argparse.Namespace(revision=revision, run_id="123")
    validate_source(run, jobs, artifacts, "FORCE_IMAGE_BUILD: true", args)
    mutations = (
        ("foreign run", lambda value: value[0]["repository"].update(full_name="other/repo")),
        ("failed run", lambda value: value[0].update(conclusion="failure")),
        ("wrong run revision", lambda value: value[0].update(head_sha="b" * 40)),
        ("wrong run ID", lambda value: value[0].update(id=456)),
        ("expired artifact", lambda value: value[2]["artifacts"][0].update(expired=True)),
    )
    import copy
    for name, mutate in mutations:
        candidate = [copy.deepcopy(run), copy.deepcopy(jobs), copy.deepcopy(artifacts)]
        mutate(candidate)
        try:
            validate_source(*candidate, "FORCE_IMAGE_BUILD: true", args)
        except ValueError:
            continue
        raise AssertionError(f"accepted {name}")
    with tempfile.TemporaryDirectory() as directory_name:
        directory = pathlib.Path(directory_name)
        for name in ("golden-path-api.tar", "golden-path-api.cdx.json", "trivy-vulnerabilities.json"):
            (directory / name).write_bytes(b"unaltered")
        artifact_args = argparse.Namespace(
            revision=revision,
            archive_sha256="0" * 64,
            sbom_sha256=digest(directory / "golden-path-api.cdx.json"),
            vulnerability_report_sha256=digest(directory / "trivy-vulnerabilities.json"),
        )
        try:
            validate_artifacts(directory, artifact_args)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted an altered archive checksum")
    attestation = [{"verificationResult": {
        "signature": {"certificate": {
            "githubWorkflowRepository": REPOSITORY, "githubWorkflowName": WORKFLOW,
            "githubWorkflowTrigger": "workflow_dispatch", "sourceRepositoryDigest": revision,
            "runInvocationURI": "https://github.com/Rano1000/platform-engineering-lab/actions/runs/123/attempts/1",
        }},
        "statement": {"subject": [{"name": "golden-path-api.tar", "digest": {"sha256": "b" * 64}}]},
    }}]
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        temporary = pathlib.Path(handle.name)
        temporary.write_text(json.dumps(attestation), encoding="utf-8")
        validate_attestation(temporary, "golden-path-api.tar", "b" * 64, revision, "123")
        wrong = json.loads(json.dumps(attestation))
        wrong[0]["verificationResult"]["signature"]["certificate"]["githubWorkflowRepository"] = "other/repo"
        temporary.write_text(json.dumps(wrong), encoding="utf-8")
        try:
            validate_attestation(temporary, "golden-path-api.tar", "b" * 64, revision, "123")
        except ValueError:
            pass
        else:
            raise AssertionError("accepted wrong attestation identity")
    print("PASS  publication rejects foreign, failed, mismatched, and expired source runs.")
    print("PASS  publication rejects an altered supplied checksum.")
    print("PASS  publication rejects incorrect attestation identity and run binding.")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    source = sub.add_parser("source")
    for name in ("run_json", "jobs_json", "artifacts_json", "run_log"):
        source.add_argument(f"--{name.replace('_', '-')}", required=True, type=pathlib.Path)
    source.add_argument("--revision", required=True)
    source.add_argument("--run-id", required=True)
    artifact = sub.add_parser("artifacts")
    artifact.add_argument("--directory", required=True, type=pathlib.Path)
    artifact.add_argument("--revision", required=True)
    for name in ("archive_sha256", "sbom_sha256", "vulnerability_report_sha256"):
        artifact.add_argument(f"--{name.replace('_', '-')}", required=True)
    attestation = sub.add_parser("attestation")
    attestation.add_argument("--result", required=True, type=pathlib.Path)
    attestation.add_argument("--subject", required=True)
    attestation.add_argument("--checksum", required=True)
    attestation.add_argument("--revision", required=True)
    attestation.add_argument("--run-id", required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "source":
            validate_source(load(args.run_json), load(args.jobs_json), load(args.artifacts_json),
                            args.run_log.read_text(encoding="utf-8"), args)
        elif args.command == "artifacts":
            require(REVISION.fullmatch(args.revision) is not None, "invalid source revision")
            for value in (args.archive_sha256, args.sbom_sha256, args.vulnerability_report_sha256):
                require(CHECKSUM.fullmatch(value) is not None, "invalid expected checksum")
            validate_artifacts(args.directory, args)
        elif args.command == "attestation":
            validate_attestation(args.result, args.subject, args.checksum, args.revision, args.run_id)
        else:
            self_test()
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
