#!/usr/bin/env python3
"""Verify relative Markdown links across the repository resolve to real files.

Offline, deterministic internal link checker. External links (http/https/mailto)
and pure anchors are skipped; fenced code blocks and inline code are ignored.
Used by ``.github/workflows/ci.yml`` and unit-tested directly.
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
}

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")

Broken = tuple[Path, str]


def _strip_code(text: str) -> str:
    text = _FENCE.sub("", text)
    return _INLINE_CODE.sub("", text)


def extract_targets(text: str) -> list[str]:
    return [m.group(1).strip() for m in _LINK.finditer(_strip_code(text))]


def is_external(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith(("http://", "https://", "mailto:", "tel:", "#"))
        or "${" in target
        or target.startswith("<")
    )


def resolve(md_file: Path, target: str) -> Path:
    # Drop any anchor or query fragment before resolving on disk.
    clean = target.split("#", 1)[0].split("?", 1)[0]
    return (md_file.parent / clean).resolve()


def check_file(md_file: Path) -> list[Broken]:
    text = md_file.read_text(encoding="utf-8", errors="ignore")
    broken: list[Broken] = []
    for target in extract_targets(text):
        if not target or is_external(target):
            continue
        clean = target.split("#", 1)[0].split("?", 1)[0]
        if not clean:  # pure anchor within the same file
            continue
        if not resolve(md_file, target).exists():
            broken.append((md_file, target))
    return broken


def iter_markdown(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else _ROOT
    broken: list[Broken] = []
    for md_file in iter_markdown(root):
        broken.extend(check_file(md_file))
    if not broken:
        print(f"All internal Markdown links resolve ({root}).")
        return 0
    for md_file, target in broken:
        rel = md_file.relative_to(root) if md_file.is_relative_to(root) else md_file
        print(f"BROKEN LINK: {rel}: {target}", file=sys.stderr)
    print(f"\n{len(broken)} broken internal link(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
