"""Guard against stale maintainer handles and non-canonical repository URLs.

The canonical GitHub owner/login is ``SoBatista`` and the canonical repository is
``github.com/SoBatista/sobatista-ai``. A prior login (``sobatistacyber``) and the
wrong repo URL must never reappear in tracked files (CODEOWNERS, docs, metadata).

Forbidden patterns are assembled by concatenation so this test file does not
itself contain a literal match.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent

# Built by concatenation on purpose (see module docstring).
STALE_HANDLE = "@sobatista" + "cyber"
OLD_REPO_URL = "github.com/sobatista" + "cyber/sobatista-ai"
OLD_PROFILE_URL = "github.com/sobatista" + "cyber"
CANONICAL_HANDLE = "@SoBatista"

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
# uv.lock legitimately pins packages by URL/name; it never references a GitHub
# owner handle, and scanning it adds noise, so skip it explicitly.
EXCLUDE_FILES = {"uv.lock"}


def _tracked_text_files() -> list[Path]:
    files: list[Path] = []
    for path in _ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        files.append(path)
    return files


def test_codeowners_uses_canonical_handle() -> None:
    codeowners = (_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert STALE_HANDLE not in codeowners, "stale CODEOWNERS handle present"
    assert CANONICAL_HANDLE in codeowners, "CODEOWNERS must name the canonical owner"


def test_no_stale_handle_or_url_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(_ROOT)
        for pattern in (STALE_HANDLE, OLD_REPO_URL, OLD_PROFILE_URL):
            if pattern in text:
                offenders.append(f"{rel}: {pattern}")
    assert not offenders, f"non-canonical handle/URL found: {offenders}"
