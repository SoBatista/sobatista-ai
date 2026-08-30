"""Installation is local-only, atomic, race-safe, and faithful to what was validated."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from sobai.core.errors import SkillError
from sobai.skills import installer
from sobai.skills.installer import (
    LOCK_FILENAME,
    STAGING_PREFIX,
    cleanup_stale_staging,
    install_skill,
    validate_source,
)
from sobai.skills.loader import load_skill_directory
from sobai.skills.registry import discover_skills

from .conftest import manifest_toml

MakeSkill = Callable[..., Path]


def test_installs_and_becomes_discoverable(make_skill_dir: MakeSkill, skills_dir: Path) -> None:
    source = make_skill_dir("demo")
    result = install_skill(source, skills_dir)
    assert result.action == "installed"
    assert result.changed
    assert (skills_dir / "demo" / "skill.toml").is_file()
    assert discover_skills(skills_dir).get("user", "demo") is not None


def test_installed_digest_matches_the_validated_digest(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    source = make_skill_dir("demo")
    validated = validate_source(source)
    installed = install_skill(source, skills_dir).skill
    reloaded = load_skill_directory(skills_dir / "demo")
    assert validated.digest == installed.digest == reloaded.digest


def test_destination_name_comes_from_the_manifest_not_the_directory(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    source = make_skill_dir("demo", dirname="some-checkout-name")
    result = install_skill(source, skills_dir)
    assert result.destination == skills_dir / "demo"


def test_reinstalling_identical_content_is_a_no_op(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    source = make_skill_dir("demo")
    install_skill(source, skills_dir)
    again = install_skill(source, skills_dir)
    assert again.action == "unchanged"
    assert not again.changed


def test_replacing_different_content_requires_force(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    install_skill(make_skill_dir("demo", prompt="First version.\n"), skills_dir)
    changed = make_skill_dir("demo", prompt="Second version.\n", dirname="demo-v2")
    with pytest.raises(SkillError, match="already installed"):
        install_skill(changed, skills_dir)
    assert "First version." in (skills_dir / "demo" / "prompt.md").read_text(encoding="utf-8")


def test_force_replaces_and_leaves_no_debris(make_skill_dir: MakeSkill, skills_dir: Path) -> None:
    install_skill(make_skill_dir("demo", prompt="First version.\n"), skills_dir)
    changed = make_skill_dir("demo", prompt="Second version.\n", dirname="demo-v2")
    result = install_skill(changed, skills_dir, force=True)
    assert result.action == "replaced"
    assert "Second version." in (skills_dir / "demo" / "prompt.md").read_text(encoding="utf-8")
    assert [p.name for p in skills_dir.iterdir()] == ["demo"]


def test_invalid_source_installs_nothing(make_skill_dir: MakeSkill, skills_dir: Path) -> None:
    source = make_skill_dir("demo", manifest="not [ toml")
    with pytest.raises(SkillError):
        install_skill(source, skills_dir)
    assert list(skills_dir.iterdir()) == []


def test_symlinked_source_is_refused_before_anything_is_written(
    make_skill_dir: MakeSkill, skills_dir: Path, tmp_path: Path
) -> None:
    real = make_skill_dir("demo")
    link = tmp_path / "link-to-demo"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SkillError, match="symbolic link"):
        install_skill(link, skills_dir)
    assert list(skills_dir.iterdir()) == []


def test_traversing_manifest_name_cannot_escape_the_skills_directory(
    make_skill_dir: MakeSkill, skills_dir: Path, tmp_path: Path
) -> None:
    source = make_skill_dir(
        "demo",
        dirname="evil",
        manifest=manifest_toml().replace('name = "demo"', 'name = "../../escaped"'),
    )
    with pytest.raises(SkillError):
        install_skill(source, skills_dir)
    assert not (tmp_path / "escaped").exists()
    assert list(skills_dir.iterdir()) == []


def test_a_concurrent_install_is_refused_not_interleaved(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    """The lock is held by another process; we refuse rather than race it."""
    (skills_dir / LOCK_FILENAME).write_text("4242", encoding="utf-8")
    with pytest.raises(SkillError, match="Another skill installation is in progress"):
        install_skill(make_skill_dir("demo"), skills_dir)
    assert list(skills_dir.glob("demo")) == []


def test_the_lock_is_released_after_a_successful_install(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    install_skill(make_skill_dir("demo"), skills_dir)
    assert not (skills_dir / LOCK_FILENAME).exists()


def test_the_lock_is_released_after_a_failed_install(
    make_skill_dir: MakeSkill, skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("sobai.skills.installer._write_staging", _boom)
    with pytest.raises(OSError, match="disk full"):
        install_skill(make_skill_dir("demo"), skills_dir)
    assert not (skills_dir / LOCK_FILENAME).exists()


def test_a_failed_replacement_rolls_back_to_the_previous_version(
    make_skill_dir: MakeSkill, skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skill(make_skill_dir("demo", prompt="First version.\n"), skills_dir)
    changed = make_skill_dir("demo", prompt="Second version.\n", dirname="demo-v2")

    real_rename = os.rename
    calls = {"n": 0}

    def _flaky_rename(src: object, dst: object) -> None:
        calls["n"] += 1
        # Let the "move the old version aside" rename succeed, then fail the
        # rename that would put the new version in place.
        if calls["n"] == 2:
            raise OSError("interrupted")
        real_rename(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr("sobai.skills.installer.os.rename", _flaky_rename)
    with pytest.raises(SkillError, match="Could not install"):
        install_skill(changed, skills_dir, force=True)

    assert (
        (skills_dir / "demo" / "prompt.md").read_text(encoding="utf-8").startswith("First version.")
    )


def test_installed_files_are_owner_only(make_skill_dir: MakeSkill, skills_dir: Path) -> None:
    install_skill(make_skill_dir("demo"), skills_dir)
    assert (skills_dir / "demo" / "skill.toml").stat().st_mode & 0o777 == 0o600
    assert (skills_dir / "demo").stat().st_mode & 0o777 == 0o700


def test_source_changed_after_validation_cannot_swap_the_content(
    make_skill_dir: MakeSkill, skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installed bytes are the reviewed bytes, not a second read of the source.

    The swap is triggered the instant validation completes, so any later read of
    the source directory would pick up the malicious content.
    """
    source = make_skill_dir("demo", prompt="Reviewed content.\n")
    real_parse = installer.parse_skill

    def _parse_then_swap(*args: object, **kwargs: object) -> object:
        parsed = real_parse(*args, **kwargs)  # type: ignore[arg-type]
        (source / "prompt.md").write_text("Malicious content.\n", encoding="utf-8")
        return parsed

    monkeypatch.setattr(installer, "parse_skill", _parse_then_swap)
    result = install_skill(source, skills_dir)

    # The swap really happened, so this test cannot pass vacuously.
    assert "Malicious content." in (source / "prompt.md").read_text(encoding="utf-8")
    installed = (skills_dir / "demo" / "prompt.md").read_text(encoding="utf-8")
    assert "Reviewed content." in installed
    assert "Malicious content." not in installed
    # And the reported digest still describes what is on disk.
    assert load_skill_directory(skills_dir / "demo").digest == result.skill.digest


def test_stale_staging_is_cleared_by_the_next_install(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    stale = skills_dir / f"{STAGING_PREFIX}interrupted"
    stale.mkdir()
    (stale / "skill.toml").write_text("partial", encoding="utf-8")
    install_skill(make_skill_dir("demo"), skills_dir)
    assert not stale.exists()
    assert (skills_dir / "demo").is_dir()


def test_cleanup_is_safe_on_a_missing_directory(tmp_path: Path) -> None:
    assert cleanup_stale_staging(tmp_path / "absent") == 0


def test_install_creates_the_skills_directory_when_absent(
    make_skill_dir: MakeSkill, tmp_path: Path
) -> None:
    target = tmp_path / "config" / "skills"
    install_skill(make_skill_dir("demo"), target)
    assert (target / "demo").is_dir()
    assert target.stat().st_mode & 0o777 == 0o700
