#!/usr/bin/env python3
# secret-scan: allow-file (this file contains only detection patterns, not secrets)
"""Deterministic, offline scan for secret-shaped strings in tracked files.

This complements GitHub's platform secret scanning by running the same check in
CI (and locally) with no network access. It looks for well-known credential
formats, not generic high-entropy strings, to keep false positives near zero.

A file may opt out by including the marker ``secret-scan: allow-file`` near its
top (used by this script and by test fixtures that legitimately embed sample
patterns). Used by ``.github/workflows/security.yml`` and unit-tested directly.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".sbomenv",
    "dist",
    "build",
    "site",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
}

ALLOW_MARKER = "secret-scan: allow-file"
MAX_BYTES = 2_000_000

# (label, compiled pattern). Patterns describe formats; none is itself a match.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{24,}")),
    ("OpenAI API key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    (
        "Private key block",
        re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    ),
]

Finding = tuple[Path, int, str]


def _is_probably_text(path: Path) -> bool:
    try:
        if path.stat().st_size > MAX_BYTES:
            return False
        with path.open("rb") as handle:
            return b"\x00" not in handle.read(4096)
    except OSError:  # pragma: no cover - unreadable file
        return False


def _iter_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def scan_file(path: Path) -> list[Finding]:
    if not _is_probably_text(path):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        return []
    head = text[:4096]
    if ALLOW_MARKER in head:
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((path, lineno, label))
    return findings


def scan_tree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files(root):
        findings.extend(scan_file(path))
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else _ROOT
    findings = scan_tree(root)
    if not findings:
        print(f"Secret scan clean ({root}).")
        return 0
    for path, lineno, label in findings:
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        print(f"POTENTIAL SECRET: {rel}:{lineno}: {label}", file=sys.stderr)
    print(f"\n{len(findings)} potential secret(s) found.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
