#!/usr/bin/env python3
"""Install and verify the repository-local, pinned Argo CD CLI."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import pathlib
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request

VERSION = "v3.5.2"
RELEASE_ROOT = f"https://github.com/argoproj/argo-cd/releases/download/{VERSION}"
CHECKSUM_NAME = "cli_checksums.txt"
CHECKSUM_SHA256 = "61de39311ec152c94a91b621465905961798ce3e0bef0871ca9ca843e22af007"
CHECKSUM_SIZE = 605
ALLOWED_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com"})
ARTIFACTS = {
    ("darwin", "amd64"): ("argocd-darwin-amd64", "9a227201004672e068aa6dacbb1d9548b71c7500e6f01e0290ed036c3ab094e0", 256780384),
    ("darwin", "arm64"): ("argocd-darwin-arm64", "6ef581f2d66b3edd178d31705639fa9b58ce820559d83cf78fef50759d821c77", 246054978),
    ("linux", "amd64"): ("argocd-linux-amd64", "d87058531d2aed735100636dd7664bdd49b862588993b571385c49494f9832c1", 249661350),
    ("linux", "arm64"): ("argocd-linux-arm64", "a8c326658c54b3a287ea25de91a8517fc4768f65ad810d918cb7444e049cea33", 236880729),
    ("linux", "ppc64le"): ("argocd-linux-ppc64le", "9de24b64cc5d60bc292c7e1f44c6428e4dd6e2b54694ea99c0e9f81b76620fcd", 245722619),
    ("linux", "s390x"): ("argocd-linux-s390x", "b6299767cc614554551e9e7316c1d39616fea00d5de354909082ab0b713a3778", 253635957),
}
ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "ppc64le": "ppc64le", "s390x": "s390x"}


class InstallError(RuntimeError):
    pass


def repository_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def platform_identity(system: str | None = None, machine: str | None = None) -> tuple[str, str]:
    selected_os = (system or platform.system()).lower()
    selected_arch = ARCHITECTURES.get((machine or platform.machine()).lower(), "")
    if (selected_os, selected_arch) not in ARTIFACTS:
        raise InstallError(f"unsupported Argo CD CLI platform: {selected_os}/{selected_arch or machine or platform.machine()}")
    return selected_os, selected_arch


def tool_path(root: pathlib.Path | None = None, identity: tuple[str, str] | None = None) -> pathlib.Path:
    selected_root = root or repository_root()
    selected_os, selected_arch = identity or platform_identity()
    return selected_root / ".tools" / "argocd" / VERSION / f"{selected_os}-{selected_arch}" / "argocd"


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_safe_destination(destination: pathlib.Path, root: pathlib.Path | None = None) -> None:
    repo = (root or repository_root()).absolute()
    expected = tool_path(repo)
    if destination.absolute() != expected:
        raise InstallError(f"unsafe Argo CD CLI destination: {destination}")
    current = repo
    for part in expected.relative_to(repo).parts:
        current /= part
        if current.exists() or current.is_symlink():
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise InstallError(f"symlink is forbidden in the CLI destination: {current}")
            if current != expected and not stat.S_ISDIR(mode):
                raise InstallError(f"non-directory CLI path component: {current}")
            if current == expected and not stat.S_ISREG(mode):
                raise InstallError(f"CLI destination is not a regular file: {current}")


def create_safe_parent(destination: pathlib.Path, root: pathlib.Path | None = None) -> None:
    repo = (root or repository_root()).absolute()
    current = repo
    for part in destination.parent.relative_to(repo).parts:
        current /= part
        if not current.exists():
            current.mkdir(mode=0o700)
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise InstallError(f"unsafe CLI directory: {current}")
        if mode & 0o022:
            raise InstallError(f"CLI directory is writable by group or others: {current}")


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise InstallError(f"release download redirected to an unexpected URL: {url}")


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self.count += 1
        if self.count > 3:
            raise InstallError("release download exceeded three redirects")
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, output: pathlib.Path, expected_size: int) -> None:
    validate_url(url)
    opener = urllib.request.build_opener(RestrictedRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "platform-engineering-lab-argocd-installer"})
    total = 0
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        with opener.open(request, timeout=60) as response:
            validate_url(response.geturl())
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) != expected_size:
                raise InstallError(f"release asset size changed: expected {expected_size}, received header {declared}")
            descriptor = os.open(output, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                total = copy_stream(response, stream)
                stream.flush()
                os.fsync(stream.fileno())
    except Exception:
        output.unlink(missing_ok=True)
        raise
    try:
        require_download_size(total, expected_size)
    except InstallError:
        output.unlink(missing_ok=True)
        raise


def copy_stream(source, destination) -> int:  # noqa: ANN001
    total = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            return total
        destination.write(chunk)
        total += len(chunk)


def require_download_size(actual: int, expected: int) -> None:
    if actual != expected:
        raise InstallError(f"incomplete release download: expected {expected} bytes, received {actual}")


def checksum_entry(manifest: pathlib.Path, filename: str) -> str:
    matches = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match:
            raise InstallError("official CLI checksum manifest is malformed")
        if match.group(2) == filename:
            matches.append(match.group(1))
    if len(matches) != 1:
        raise InstallError(f"official checksum manifest must contain exactly one entry for {filename}")
    return matches[0]


def cli_version(binary: pathlib.Path) -> str:
    result = subprocess.run([str(binary), "version", "--client", "--short"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
    if result.returncode != 0:
        raise InstallError("downloaded Argo CD CLI could not report its version")
    match = re.search(r"\b(v\d+\.\d+\.\d+)(?:\+[^\s]+)?\b", result.stdout)
    if not match or match.group(1) != VERSION:
        raise InstallError(f"Argo CD CLI version mismatch: expected {VERSION}, found {result.stdout.strip() or 'unknown'}")
    return match.group(1)


def verify_binary(destination: pathlib.Path, expected_checksum: str, expected_size: int, check_version: bool = True) -> None:
    ensure_safe_destination(destination)
    mode = destination.lstat().st_mode
    if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
        raise InstallError("repository-local Argo CD CLI must be a regular file")
    if destination.stat().st_size != expected_size:
        raise InstallError("repository-local Argo CD CLI has an unexpected size")
    actual = sha256(destination)
    if actual != expected_checksum:
        raise InstallError(f"repository-local Argo CD CLI checksum mismatch: {actual}")
    if check_version:
        cli_version(destination)


def install() -> pathlib.Path:
    identity = platform_identity()
    filename, expected_checksum, expected_size = ARTIFACTS[identity]
    destination = tool_path(identity=identity)
    ensure_safe_destination(destination)
    if destination.exists():
        verify_binary(destination, expected_checksum, expected_size)
        return destination
    create_safe_parent(destination)
    ensure_safe_destination(destination)
    temporary = pathlib.Path(tempfile.mkdtemp(prefix=".install-", dir=destination.parent))
    os.chmod(temporary, 0o700)
    try:
        manifest = temporary / CHECKSUM_NAME
        artifact = temporary / filename
        download(f"{RELEASE_ROOT}/{CHECKSUM_NAME}", manifest, CHECKSUM_SIZE)
        if sha256(manifest) != CHECKSUM_SHA256:
            raise InstallError("official CLI checksum manifest failed its pinned SHA-256")
        manifest_checksum = checksum_entry(manifest, filename)
        if manifest_checksum != expected_checksum:
            raise InstallError("official checksum manifest differs from the repository pin")
        download(f"{RELEASE_ROOT}/{filename}", artifact, expected_size)
        if sha256(artifact) != expected_checksum:
            raise InstallError("downloaded Argo CD CLI failed SHA-256 verification")
        cli_version(artifact)
        os.chmod(artifact, 0o750)
        os.replace(artifact, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        verify_binary(destination, expected_checksum, expected_size)
    finally:
        shutil.rmtree(temporary)
    return destination


def expect_failure(action, label: str) -> None:
    try:
        action()
    except (InstallError, FileNotFoundError):
        return
    raise AssertionError(f"{label} was accepted")


def self_test() -> None:
    assert platform_identity("Linux", "x86_64") == ("linux", "amd64")
    expect_failure(lambda: platform_identity("Linux", "mips64"), "unsupported architecture")
    expect_failure(lambda: validate_url("https://example.com/argocd"), "unexpected redirect host")
    output = io.BytesIO()
    copied = copy_stream(io.BytesIO(b"short"), output)
    assert copied == 5 and copied != 100 and output.getvalue() == b"short"
    expect_failure(lambda: require_download_size(copied, 100), "incomplete download")
    with tempfile.TemporaryDirectory() as value:
        root = pathlib.Path(value)
        destination = tool_path(root, ("linux", "amd64"))
        destination.parent.mkdir(parents=True)
        expect_failure(lambda: verify_binary(destination, "0" * 64, 8, check_version=False), "missing CLI")
        destination.write_bytes(b"truncated")
        expect_failure(lambda: verify_binary(destination, hashlib.sha256(b"truncated").hexdigest(), 100, check_version=False), "truncated CLI")
        expect_failure(lambda: verify_binary(destination, "0" * 64, len(b"truncated"), check_version=False), "checksum mismatch")
        destination.unlink()
        payload = destination.parent / "fixture"
        payload.write_bytes(b"complete")
        destination.symlink_to(payload)
        expect_failure(lambda: ensure_safe_destination(destination, root), "symlink destination")
        expect_failure(lambda: ensure_safe_destination(root / ".tools" / "../escape", root), "unsafe destination")
    with tempfile.TemporaryDirectory() as value:
        wrong_version = pathlib.Path(value) / "argocd"
        wrong_version.write_text("#!/bin/sh\nprintf '%s\\n' 'argocd: v3.5.1+fixture'\n", encoding="utf-8")
        wrong_version.chmod(0o700)
        expect_failure(lambda: cli_version(wrong_version), "version mismatch")
    with tempfile.TemporaryDirectory() as value:
        manifest = pathlib.Path(value) / CHECKSUM_NAME
        manifest.write_text("0" * 64 + "  argocd-linux-amd64\n", encoding="utf-8")
        assert checksum_entry(manifest, "argocd-linux-amd64") == "0" * 64
    print("PASS  Argo CD CLI installer rejects version, checksum, architecture, truncation, redirect, and path failures.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("install", "path", "verify", "self-test"))
    args = parser.parse_args()
    try:
        if args.command == "install":
            print(install())
        elif args.command == "path":
            print(tool_path())
        elif args.command == "verify":
            identity = platform_identity()
            _, checksum, size = ARTIFACTS[identity]
            destination = tool_path(identity=identity)
            verify_binary(destination, checksum, size)
            print(destination)
        else:
            self_test()
    except (InstallError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
