#!/usr/bin/env python3
"""Extract and compile every Python heredoc embedded in repository shell scripts."""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
START = re.compile(r"\bpython3\b[^\n]*<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1\s*$")


def extracts(path: pathlib.Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        match = START.search(lines[index])
        if not match:
            index += 1
            continue
        delimiter = match.group(2)
        start = index + 2
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].lstrip("\t") != delimiter:
            body.append(lines[index].lstrip("\t") if "<<-" in lines[start - 2] else lines[index])
            index += 1
        if index == len(lines):
            raise SyntaxError(f"{path.relative_to(ROOT)}:{start - 1}: unterminated Python heredoc {delimiter}")
        blocks.append((start, "\n".join(body) + "\n"))
        index += 1
    return blocks


def main() -> None:
    count = 0
    for path in sorted((ROOT / "scripts").rglob("*.sh")):
        for line, source in extracts(path):
            compile(source, f"{path.relative_to(ROOT)}:heredoc:{line}", "exec")
            count += 1
    if count == 0:
        raise SystemExit("FAIL  no embedded Python heredocs were discovered")
    print(f"PASS  compiled {count} embedded Python heredoc(s) from repository shell scripts.")


if __name__ == "__main__":
    main()
