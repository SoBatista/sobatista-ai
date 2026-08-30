"""`/skills` in the interactive session: discovery only, never execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sobai.cli.session import _SLASH_COMMANDS, InteractiveSession
from sobai.core.context import AppContext, GlobalOptions

from .conftest import manifest_toml


@pytest.fixture
def session(env: dict[str, str]) -> InteractiveSession:
    return InteractiveSession(AppContext.build(GlobalOptions()))


def test_skills_is_an_offered_command() -> None:
    assert "/skills" in _SLASH_COMMANDS


def test_help_mentions_skills(
    session: InteractiveSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.handle_slash("/help")
    assert "/skills" in capsys.readouterr().out


def test_skills_lists_builtins_and_points_at_the_command(
    session: InteractiveSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert session.handle_slash("/skills") is True
    out = capsys.readouterr().out
    assert "builtin:summarize" in out
    assert "sobai run NAME" in out
    assert "not run inside this session" in out


def test_skills_lists_user_skills_too(
    session: InteractiveSession, env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    directory = Path(env["SOBAI_CONFIG_DIR"]) / "skills" / "mine"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "skill.toml").write_text(manifest_toml(name="mine"), encoding="utf-8")
    (directory / "prompt.md").write_text("Do my thing.\n", encoding="utf-8")
    session.handle_slash("/skills")
    assert "user:mine" in capsys.readouterr().out


def test_skills_warns_about_a_broken_user_skill(
    session: InteractiveSession, env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    directory = Path(env["SOBAI_CONFIG_DIR"]) / "skills" / "broken"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "skill.toml").write_text("not [ toml", encoding="utf-8")
    (directory / "prompt.md").write_text("x\n", encoding="utf-8")
    session.handle_slash("/skills")
    captured = capsys.readouterr()
    assert "user:broken" in captured.err


def test_skills_does_not_run_anything(
    session: InteractiveSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery must not construct a provider or send a prompt."""

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("/skills must not build a provider")

    monkeypatch.setattr("sobai.cli.session.build_provider", _explode)
    assert session.handle_slash("/skills") is True
    assert session.turns == 0
    assert session.messages == []


def test_skills_takes_no_argument_that_could_select_one(
    session: InteractiveSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`/skills summarize` lists, it does not activate or run a skill."""

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("/skills must not build a provider")

    monkeypatch.setattr("sobai.cli.session.build_provider", _explode)
    session.handle_slash("/skills summarize")
    assert "builtin:summarize" in capsys.readouterr().out
    assert session.messages == []
