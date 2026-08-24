"""Tests for the one-PR-one-version release policy tooling.

Covers ``scripts/check_version.py`` (what a pull request must declare) and the
pure parts of ``scripts/release.py`` (what may be turned into a tag).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.check_version import (
    VersionError,
    changelog_has_section,
    check_consistency,
    next_version,
    parse_semver,
    selected_bump,
)
from scripts.release import ReleaseError, build_plan, newest_tag, release_notes


# --------------------------------------------------------------------------- #
# version arithmetic
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("base", "bump", "expected"),
    [
        ("0.1.0", "patch", "0.1.1"),
        ("0.1.0", "minor", "0.2.0"),
        ("0.1.0", "major", "1.0.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
        ("0.9.9", "minor", "0.10.0"),
    ],
)
def test_next_version(base: str, bump: str, expected: str) -> None:
    assert next_version(base, bump) == expected


def test_pre_1_0_has_no_special_cases() -> None:
    """The whole point of the migration: a minor pre-1.0 is a real minor."""
    assert next_version("0.1.1", "minor") == "0.2.0"
    assert next_version("0.1.1", "major") == "1.0.0"


@pytest.mark.parametrize("value", ["1.2", "v1.2.3", "1.2.3.4", "01.2.3", "", "1.2.3-rc1"])
def test_parse_semver_rejects(value: str) -> None:
    with pytest.raises(VersionError):
        parse_semver(value)


# --------------------------------------------------------------------------- #
# label selection
# --------------------------------------------------------------------------- #
def test_selected_bump_exactly_one() -> None:
    assert selected_bump("release:minor") == "minor"
    assert selected_bump("bug,release:patch,documentation") == "patch"


@pytest.mark.parametrize("labels", ["", "bug", "release:none", "releaseminor"])
def test_selected_bump_requires_one(labels: str) -> None:
    with pytest.raises(VersionError, match="exactly one label"):
        selected_bump(labels)


def test_selected_bump_rejects_several() -> None:
    with pytest.raises(VersionError, match="multiple release labels"):
        selected_bump("release:minor,release:patch")


# --------------------------------------------------------------------------- #
# consistency across every place the version is recorded
# --------------------------------------------------------------------------- #
def _tree(
    root: Path,
    version: str,
    *,
    lock: str | None = None,
    fallback: str | None = None,
    dated: bool = True,
) -> Path:
    (root / "src" / "sobai").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "sobatista-ai"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "src" / "sobai" / "__init__.py").write_text(
        f'_FALLBACK_VERSION = "{fallback or version}"\n', encoding="utf-8"
    )
    (root / "uv.lock").write_text(
        f'[[package]]\nname = "sobatista-ai"\nversion = "{lock or version}"\n'
        'source = {{ editable = "." }}\n'.replace("{{", "{").replace("}}", "}"),
        encoding="utf-8",
    )
    heading = f"## [{version}] - 2026-08-24" if dated else f"## {version} (2026-08-24)"
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n{heading}\n\n- a change\n", encoding="utf-8"
    )
    return root


def test_consistency_passes(tmp_path: Path) -> None:
    assert check_consistency(_tree(tmp_path, "0.2.0")) == "0.2.0"


def test_consistency_catches_stale_lockfile(tmp_path: Path) -> None:
    with pytest.raises(VersionError, match=r"uv\.lock"):
        check_consistency(_tree(tmp_path, "0.2.0", lock="0.1.9"))


def test_consistency_catches_stale_fallback(tmp_path: Path) -> None:
    with pytest.raises(VersionError, match="_FALLBACK_VERSION"):
        check_consistency(_tree(tmp_path, "0.2.0", fallback="0.1.9"))


def test_consistency_requires_dated_changelog_section(tmp_path: Path) -> None:
    with pytest.raises(VersionError, match="no dated section"):
        check_consistency(_tree(tmp_path, "0.2.0", dated=False))


def test_changelog_section_detection(tmp_path: Path) -> None:
    root = _tree(tmp_path, "0.2.0")
    assert changelog_has_section("0.2.0", root)
    assert not changelog_has_section("0.3.0", root)


def test_repo_itself_is_consistent() -> None:
    """The live tree must always satisfy the policy it enforces."""
    assert check_consistency()


# --------------------------------------------------------------------------- #
# release planning
# --------------------------------------------------------------------------- #
def test_release_notes_extracted_from_reviewed_section(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n"
        "## [0.2.0] - 2026-08-24\n\n### Added\n- the new thing\n\n"
        "## [0.1.0] - 2026-08-23\n\n- the old thing\n",
        encoding="utf-8",
    )
    assert release_notes("0.2.0", tmp_path) == "### Added\n- the new thing"
    assert release_notes("0.1.0", tmp_path) == "- the old thing"


def test_release_notes_empty_section_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.2.0] - 2026-08-24\n\n## [0.1.0] - 2026-08-23\n\n- old\n",
        encoding="utf-8",
    )
    with pytest.raises(ReleaseError, match="empty"):
        release_notes("0.2.0", tmp_path)


def _git_repo(root: Path, tags: list[str]) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (root / "f").write_text("x", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "c")
    for tag in tags:
        git("tag", tag)
    return root


def _commit(root: Path, message: str) -> None:
    (root / message).write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True, capture_output=True)


def test_newest_tag_orders_numerically(tmp_path: Path) -> None:
    root = _git_repo(tmp_path, ["v0.9.0", "v0.10.0", "v0.2.0"])
    assert newest_tag("v1.0.0", root) == "v0.10.0"


def test_newest_tag_recognises_the_legacy_prefixed_tag(tmp_path: Path) -> None:
    """v0.1.0 was tagged by Release Please as sobatista-ai-v0.1.0."""
    root = _git_repo(tmp_path, ["sobatista-ai-v0.1.0"])
    assert newest_tag("v0.1.1", root) == "sobatista-ai-v0.1.0"


def test_newest_tag_ignores_unrelated_tags(tmp_path: Path) -> None:
    root = _git_repo(tmp_path, ["nightly", "release-candidate"])
    assert newest_tag("v0.1.1", root) is None


def test_plan_refuses_to_move_an_existing_tag(tmp_path: Path) -> None:
    """A tag pointing at another commit is a hard failure, never a move."""
    root = _git_repo(_tree(tmp_path, "0.2.0"), [])
    _commit(root, "second")
    subprocess.run(["git", "tag", "v0.2.0", "HEAD~1"], cwd=root, check=True, capture_output=True)
    with pytest.raises(ReleaseError, match="Refusing to move it"):
        build_plan(root)


def test_plan_refuses_a_version_that_is_not_newer(tmp_path: Path) -> None:
    root = _git_repo(_tree(tmp_path, "0.2.0"), ["v0.3.0"])
    with pytest.raises(ReleaseError, match="not newer than"):
        build_plan(root)


def test_plan_describes_a_clean_release(tmp_path: Path) -> None:
    root = _git_repo(_tree(tmp_path, "0.2.0"), ["v0.1.0"])
    plan = build_plan(root)
    assert (plan.version, plan.tag, plan.needs_tag) == ("0.2.0", "v0.2.0", True)


def test_plan_is_idempotent_when_the_tag_is_already_here(tmp_path: Path) -> None:
    """A CI re-run on an already-released commit must not fail."""
    root = _git_repo(_tree(tmp_path, "0.2.0"), ["v0.2.0"])
    assert build_plan(root).needs_tag is False
