#!/usr/bin/env python3
"""Create fail-closed diagnostic directories without following symlinks."""

from __future__ import annotations

import argparse
import os
import pathlib
import tempfile


def absolute_lexical(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(os.path.abspath(path))


def ensure_directory(base_raw: str, root_raw: str, destination_raw: str) -> pathlib.Path:
    base = absolute_lexical(pathlib.Path(base_raw))
    root = absolute_lexical(pathlib.Path(root_raw))
    destination = absolute_lexical(pathlib.Path(destination_raw))
    try:
        root.relative_to(base)
        destination.relative_to(root)
    except ValueError as error:
        raise ValueError("diagnostic path escapes its approved run directory") from error
    current = pathlib.Path(base.anchor)
    for part in base.parts[1:] + root.relative_to(base).parts + destination.relative_to(root).parts:
        current /= part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise ValueError(f"diagnostic directory component is unsafe: {current}")
        else:
            current.mkdir()
    return destination


def ensure_output(base_raw: str, root_raw: str, output_raw: str) -> pathlib.Path:
    output = absolute_lexical(pathlib.Path(output_raw))
    ensure_directory(base_raw, root_raw, str(output.parent))
    if output.exists() or output.is_symlink():
        if output.is_symlink() or not output.is_file():
            raise ValueError(f"diagnostic output is not a regular file: {output}")
    return output


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = pathlib.Path(temporary) / "artifact base"
        root = base / "run + safe_1"
        first = ensure_directory(str(base), str(root), str(root / "pods" / "pod one"))
        second = ensure_directory(str(base), str(root), str(root / "pods" / "pod_[two]"))
        assert first.is_dir() and second.is_dir() and first != second
        pod_json = first / "pod.json"; pod_json.write_text("{}")
        ensure_output(str(base), str(root), str(pod_json))
        try: ensure_directory(str(base), str(root), str(pod_json / "pod.log"))
        except ValueError: pass
        else: raise AssertionError("pod.json became a directory parent")
        try: ensure_directory(str(base), str(root), str(root / ".." / "escaped"))
        except ValueError: pass
        else: raise AssertionError("traversal escaped the run directory")
        collision = pathlib.Path(str(root) + "-other")
        try: ensure_directory(str(base), str(root), str(collision))
        except ValueError: pass
        else: raise AssertionError("prefix-collision directory escaped the run directory")
        outside = pathlib.Path(temporary) / "outside"
        try: ensure_directory(str(base), str(root), str(outside))
        except ValueError: pass
        else: raise AssertionError("absolute outside path escaped the run directory")
        link = root / "linked"; link.symlink_to(pathlib.Path(temporary))
        try: ensure_directory(str(base), str(root), str(link / "child"))
        except ValueError: pass
        else: raise AssertionError("symlink traversal was accepted")
        fifo = root / "fifo"; os.mkfifo(fifo)
        try: ensure_output(str(base), str(root), str(fifo))
        except ValueError: pass
        else: raise AssertionError("special-file output was accepted")
    print("PASS  diagnostic paths support safe unusual names and reject collisions, traversal, symlinks, and non-directory components.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("ensure-dir", "ensure-output", "self-test"))
    parser.add_argument("--base")
    parser.add_argument("--root")
    parser.add_argument("--path")
    args = parser.parse_args()
    if args.command == "self-test": self_test(); return
    if not args.base or not args.root or not args.path: parser.error("--base, --root, and --path are required")
    try:
        if args.command == "ensure-dir": ensure_directory(args.base, args.root, args.path)
        else: ensure_output(args.base, args.root, args.path)
    except ValueError as error:
        raise SystemExit("FAIL  " + str(error)) from error


if __name__ == "__main__": main()
