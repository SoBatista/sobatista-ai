#!/usr/bin/env python3
"""Validate the version a pull request declares, and where it is recorded.

Every pull request carries its own version bump, so the version reaching ``main``
is the one that was reviewed. This script is what makes that reviewable claim
enforceable. It has two modes:

``--consistency`` asserts that every place recording the version agrees and that
the changelog documents it. ``[project].version`` in ``pyproject.toml`` is the
single source of truth; ``_FALLBACK_VERSION`` in ``src/sobai/__init__.py`` and
the workspace entry in ``uv.lock`` must match it, and ``CHANGELOG.md`` must carry
a dated ``## [x.y.z] - YYYY-MM-DD`` section for it.

``--pr BASE_REF`` additionally requires exactly one ``release:*`` label in the
``RELEASE_LABELS`` environment variable and proves the version is exactly that
one SemVer increment from the version at ``BASE_REF``.

Labels arrive through the environment and the base ref through argv — never
interpolated into a shell — so untrusted pull-request metadata cannot be
executed. Run by ``.github/workflows/pr-release-metadata.yml`` and unit-tested
directly.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

BUMPS = ("major", "minor", "patch")
LABEL_PREFIX = "release:"

_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_FALLBACK_RE = re.compile(r"""^_FALLBACK_VERSION\s*=\s*["']([^"']+)["']""", re.MULTILINE)
_LOCK_RE = re.compile(r'^\[\[package\]\]\nname = "sobatista-ai"\nversion = "([^"]+)"', re.MULTILINE)


class VersionError(Exception):
    """A version fact is missing, malformed, or inconsistent."""


def parse_semver(value: str) -> tuple[int, int, int]:
    """Return ``(major, minor, patch)``; raise if ``value`` is not exact SemVer."""
    match = _SEMVER_RE.match(value.strip())
    if not match:
        raise VersionError(f"not a SemVer version: {value!r}")
    return int(match[1]), int(match[2]), int(match[3])


def next_version(base: str, bump: str) -> str:
    """Return the single ``bump`` increment from ``base``."""
    major, minor, patch = parse_semver(base)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise VersionError(f"unknown bump: {bump!r}")


def selected_bump(labels: str) -> str:
    """Return the one release bump named in ``labels``; raise otherwise."""
    present = [b for b in BUMPS if f"{LABEL_PREFIX}{b}" in _split_labels(labels)]
    if len(present) == 1:
        return present[0]
    if not present:
        raise VersionError(
            "a pull request needs exactly one label: "
            + ", ".join(f"{LABEL_PREFIX}{b}" for b in BUMPS)
        )
    raise VersionError(f"multiple release labels ({', '.join(present)}); apply exactly one.")


def _split_labels(labels: str) -> set[str]:
    return {part.strip() for part in labels.split(",") if part.strip()}


def read_project_version(root: Path | None = None) -> str:
    """Return ``[project].version`` — the single source of truth."""
    path = (root or _ROOT) / "pyproject.toml"
    version = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
    if not isinstance(version, str):  # pragma: no cover - defensive
        raise VersionError("project.version is not a string")
    return version


def read_fallback_version(root: Path | None = None) -> str:
    """Return ``_FALLBACK_VERSION`` from the package's ``__init__``."""
    path = (root or _ROOT) / "src" / "sobai" / "__init__.py"
    match = _FALLBACK_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise VersionError("no _FALLBACK_VERSION found in src/sobai/__init__.py")
    return match[1]


def read_lock_version(root: Path | None = None) -> str:
    """Return the version ``uv.lock`` records for this workspace package."""
    path = (root or _ROOT) / "uv.lock"
    match = _LOCK_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise VersionError("no sobatista-ai package entry found in uv.lock")
    return match[1]


def changelog_has_section(version: str, root: Path | None = None) -> bool:
    """Return True when CHANGELOG.md carries a dated section for ``version``."""
    path = (root or _ROOT) / "CHANGELOG.md"
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\] - [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$",
        re.MULTILINE,
    )
    return bool(pattern.search(path.read_text(encoding="utf-8")))


def check_consistency(root: Path | None = None) -> str:
    """Assert every recorded version agrees and is documented; return it."""
    version = read_project_version(root)
    parse_semver(version)

    for name, found in (
        ("src/sobai/__init__.py (_FALLBACK_VERSION)", read_fallback_version(root)),
        ("uv.lock", read_lock_version(root)),
    ):
        if found != version:
            raise VersionError(
                f"{name} records {found!r}, but pyproject.toml declares {version!r}. "
                "Run `uv lock` and update the fallback constant."
            )

    if not changelog_has_section(version, root):
        raise VersionError(
            f"CHANGELOG.md has no dated section for {version}. Add `## [{version}] - YYYY-MM-DD`."
        )
    return version


def version_at_ref(ref: str, root: Path | None = None) -> str:
    """Return ``[project].version`` as of ``ref``, or 0.0.0 before it existed."""
    result = subprocess.run(  # noqa: S603 - argv array, never a shell string
        ["git", "show", f"{ref}:pyproject.toml"],  # noqa: S607 - git from PATH
        cwd=str(root or _ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise VersionError(f"base ref not found: {ref}. Fetch it first (e.g. git fetch origin).")
    version = tomllib.loads(result.stdout)["project"]["version"]
    return str(version)


def check_pr(base_ref: str, labels: str, root: Path | None = None) -> str:
    """Assert the version is exactly the labelled increment from ``base_ref``."""
    current = check_consistency(root)
    bump = selected_bump(labels)
    base = version_at_ref(base_ref, root)
    expected = next_version(base, bump)
    if current != expected:
        raise VersionError(
            f"{LABEL_PREFIX}{bump} requires version {expected}; found {current} (base {base})."
        )
    return f"release metadata passed: {base} -> {current} ({bump})"


def main(argv: list[str]) -> int:
    args = argv[1:] or ["--consistency"]
    try:
        if args == ["--consistency"]:
            print(f"version consistency passed: {check_consistency()}")
            return 0
        if len(args) == 2 and args[0] == "--pr":
            print(check_pr(args[1], os.environ.get("RELEASE_LABELS", "")))
            return 0
    except VersionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "usage: check_version.py [--consistency | --pr BASE_REF]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
