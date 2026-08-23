#!/usr/bin/env python3
"""Verify the release tag matches the packaged version.

Given a git tag (e.g. ``v0.1.0`` or ``v0.1.0a1``), assert that, after stripping
a leading ``v``, it identifies the same version as ``[project].version`` in
``pyproject.toml``. Comparison is PEP 440-normalized when ``packaging`` is
available, otherwise an exact string match. Used by ``release.yml`` and
unit-tested directly.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def read_project_version(pyproject: Path | None = None) -> str:
    path = pyproject or (_ROOT / "pyproject.toml")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    version = data["project"]["version"]
    if not isinstance(version, str):  # pragma: no cover - defensive
        raise TypeError("project.version is not a string")
    return version


def normalize(value: str) -> str:
    """Best-effort PEP 440 normalization; falls back to the raw string."""
    try:
        from packaging.version import Version
    except ModuleNotFoundError:  # pragma: no cover - packaging usually present
        return value.strip()
    return str(Version(value))


def tag_matches(tag: str, version: str) -> bool:
    candidate = tag[1:] if tag.startswith(("v", "V")) else tag
    if candidate.strip() == version.strip():
        return True
    try:
        return normalize(candidate) == normalize(version)
    except Exception:
        # An unparseable tag is simply a mismatch, not a crash.
        return False


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].strip():
        print("usage: check_version_tag.py <tag>", file=sys.stderr)
        return 2
    tag = argv[1].strip()
    version = read_project_version()
    if tag_matches(tag, version):
        print(f"OK: tag {tag} matches packaged version {version}")
        return 0
    print(
        f"ERROR: tag {tag!r} does not match packaged version {version!r}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
