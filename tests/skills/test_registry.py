"""Namespaces, resolution, and the refusal to let a user Skill shadow a built-in."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from sobai.core.errors import AmbiguousSkillError, SkillError, SkillNotFoundError
from sobai.skills.loader import parse_skill
from sobai.skills.models import Namespace
from sobai.skills.registry import SkillRegistry, discover_skills

from .conftest import MINIMAL_PROMPT, manifest_toml

MakeSkill = Callable[..., Path]


def _skill(name: str, namespace: str, version: str = "1.0.0") -> object:
    return parse_skill(
        manifest_toml(name=name, version=version).encode(),
        MINIMAL_PROMPT.encode(),
        namespace=namespace,
    )


def registry_with(*pairs: tuple[str, str]) -> SkillRegistry:
    registry = SkillRegistry()
    for name, namespace in pairs:
        registry.add(_skill(name, namespace))  # type: ignore[arg-type]
    return registry


# -- resolution ------------------------------------------------------------
def test_short_name_resolves_when_unambiguous() -> None:
    registry = registry_with(("summarize", Namespace.BUILTIN))
    assert registry.resolve("summarize").qualified_name == "builtin:summarize"


def test_qualified_name_resolves_exactly() -> None:
    registry = registry_with(("summarize", Namespace.BUILTIN), ("summarize", Namespace.USER))
    assert registry.resolve("user:summarize").namespace == Namespace.USER
    assert registry.resolve("builtin:summarize").namespace == Namespace.BUILTIN


def test_a_user_skill_never_silently_shadows_a_builtin() -> None:
    """The central rule: same short name in both namespaces is an error, not a preference."""
    registry = registry_with(
        ("security-review", Namespace.BUILTIN), ("security-review", Namespace.USER)
    )
    with pytest.raises(AmbiguousSkillError) as excinfo:
        registry.resolve("security-review")
    message = excinfo.value.message
    assert "builtin:security-review" in message
    assert "user:security-review" in message
    assert excinfo.value.hint is not None
    assert "fully qualified" in excinfo.value.hint


def test_ambiguity_survives_a_higher_user_version() -> None:
    """A user Skill cannot win by claiming a newer version."""
    registry = registry_with(
        ("summarize", Namespace.BUILTIN),
        ("summarize", Namespace.USER),
    )
    registry.add(_skill("summarize", Namespace.USER, version="99.0.0"))  # type: ignore[arg-type]
    with pytest.raises(AmbiguousSkillError):
        registry.resolve("summarize")


def test_unknown_name_reports_not_found() -> None:
    registry = registry_with(("summarize", Namespace.BUILTIN))
    with pytest.raises(SkillNotFoundError, match="No skill named"):
        registry.resolve("nope-not-here")


def test_not_found_hint_suggests_a_near_match() -> None:
    registry = registry_with(("summarize", Namespace.BUILTIN))
    with pytest.raises(SkillNotFoundError) as excinfo:
        registry.resolve("summarise")
    assert "summarize" in (excinfo.value.hint or "")


def test_unknown_namespace_is_refused() -> None:
    registry = registry_with(("summarize", Namespace.BUILTIN))
    with pytest.raises(SkillError, match="Unknown skill namespace"):
        registry.resolve("system:summarize")


def test_empty_reference_is_refused() -> None:
    with pytest.raises(SkillNotFoundError):
        SkillRegistry().resolve("   ")


@pytest.mark.parametrize("reference", ["../etc/passwd", "a/b", "Summarize", "user:../x", "user:"])
def test_illegal_references_are_refused(reference: str) -> None:
    registry = registry_with(("summarize", Namespace.BUILTIN))
    with pytest.raises(SkillError):
        registry.resolve(reference)


def test_listing_puts_builtins_first_then_alphabetical() -> None:
    registry = registry_with(
        ("zeta", Namespace.USER),
        ("alpha", Namespace.USER),
        ("omega", Namespace.BUILTIN),
        ("beta", Namespace.BUILTIN),
    )
    assert [s.qualified_name for s in registry.list()] == [
        "builtin:beta",
        "builtin:omega",
        "user:alpha",
        "user:zeta",
    ]


# -- discovery -------------------------------------------------------------
def test_discovery_finds_user_skills(make_skill_dir: MakeSkill, skills_dir: Path) -> None:
    make_skill_dir("mine", root=skills_dir)
    registry = discover_skills(skills_dir)
    assert registry.get(Namespace.USER, "mine") is not None


def test_discovery_tolerates_a_missing_directory(tmp_path: Path) -> None:
    registry = discover_skills(tmp_path / "not-created")
    assert registry.broken == []


def test_discovery_without_a_user_directory_returns_builtins_only() -> None:
    registry = discover_skills(None)
    assert all(s.namespace == Namespace.BUILTIN for s in registry.list())


def test_one_broken_skill_does_not_hide_the_others(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    make_skill_dir("good", root=skills_dir)
    broken = skills_dir / "broken"
    broken.mkdir()
    (broken / "skill.toml").write_text("not [ valid toml", encoding="utf-8")
    (broken / "prompt.md").write_text("hi", encoding="utf-8")

    registry = discover_skills(skills_dir)
    assert registry.get(Namespace.USER, "good") is not None
    assert [b.qualified_name for b in registry.broken] == ["user:broken"]
    assert "TOML" in registry.broken[0].reason


def test_discovery_ignores_installer_scratch_directories(
    make_skill_dir: MakeSkill, skills_dir: Path
) -> None:
    make_skill_dir("good", root=skills_dir)
    (skills_dir / ".staging-abc").mkdir()
    (skills_dir / "_private").mkdir()
    registry = discover_skills(skills_dir)
    assert [s.qualified_name for s in registry.list()] == ["user:good"]
    assert registry.broken == []


def test_discovery_records_a_symlinked_user_skill_as_broken(
    make_skill_dir: MakeSkill, skills_dir: Path, tmp_path: Path
) -> None:
    real = make_skill_dir("elsewhere")
    os.symlink(real, skills_dir / "elsewhere", target_is_directory=True)
    registry = discover_skills(skills_dir)
    assert registry.skills == {}
    assert "symbolic link" in registry.broken[0].reason


def test_discovery_never_reads_the_current_directory(
    make_skill_dir: MakeSkill, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository you happen to run inside cannot supply a Skill."""
    repo = tmp_path / "untrusted-repo"
    for candidate in ("skills", ".sobai/skills"):
        make_skill_dir("evil", root=repo / candidate)
    monkeypatch.chdir(repo)
    registry = discover_skills(None)
    assert registry.get(Namespace.USER, "evil") is None
    assert all(s.namespace == Namespace.BUILTIN for s in registry.list())


def test_discovery_ignores_environment_pointed_directories(
    make_skill_dir: MakeSkill, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    make_skill_dir("injected", root=elsewhere)
    for var in ("SOBAI_SKILLS_DIR", "SOBAI_SKILLS_PATH", "FABRIC_PATTERNS_DIR"):
        monkeypatch.setenv(var, str(elsewhere))
    registry = discover_skills(None)
    assert registry.get(Namespace.USER, "injected") is None
