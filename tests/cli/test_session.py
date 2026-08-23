"""Tests for the interactive `sobai` session (no real TTY, mocked providers)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sobai.cli import session as session_mod
from sobai.cli.app import app
from sobai.cli.session import InteractiveSession
from sobai.core.context import AppContext, GlobalOptions
from sobai.core.errors import (
    LocalOnlyViolation,
    ProviderError,
    ProviderUnavailableError,
    SobaiError,
)
from sobai.core.types import (
    Completion,
    GenerateParams,
    StopReason,
    StreamEvent,
    StreamEventType,
    Usage,
)
from sobai.providers.base import Provider, ProviderHealth


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOBAI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SOBAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOBAI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NO_COLOR", "1")


def make_app(**opts: Any) -> AppContext:
    return AppContext.build(GlobalOptions(**opts))


class FakeProvider(Provider):
    is_local = True

    def __init__(
        self,
        *,
        name: str = "ollama",
        text: str = "reply",
        chunks: list[str] | None = None,
        usage: Usage | None = None,
        fail: Exception | None = None,
        stream_deltas: bool = True,
    ) -> None:
        self.name = name
        self.is_local = name == "ollama"
        self._text = text
        self._chunks = chunks if chunks is not None else [text]
        self._usage = usage or Usage(input_tokens=1, output_tokens=2)
        self._fail = fail
        self._stream_deltas = stream_deltas
        self.calls = 0
        self.last_params: GenerateParams | None = None

    async def generate(self, params: GenerateParams) -> Completion:
        self.calls += 1
        self.last_params = params
        if self._fail:
            raise self._fail
        return Completion(text=self._text, usage=self._usage, stop_reason=StopReason.END_TURN)

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        self.last_params = params
        if self._fail:
            raise self._fail
        if self._stream_deltas:
            for c in self._chunks:
                yield StreamEvent(type=StreamEventType.TEXT, text=c)
        yield StreamEvent(
            type=StreamEventType.DONE,
            completion=Completion(text=self._text, usage=self._usage),
        )

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


def reader_from(lines: list[str | type]):  # type: ignore[no-untyped-def]
    """Build a reader that yields lines; EOFError/KeyboardInterrupt sentinels raise."""
    it = iter(lines)

    def _read(_prompt: str) -> str:
        try:
            item = next(it)
        except StopIteration:
            raise EOFError from None
        if item is EOFError:
            raise EOFError
        if item is KeyboardInterrupt:
            raise KeyboardInterrupt
        return item  # type: ignore[return-value]

    return _read


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
def test_non_tty_dispatch_guides(runner: CliRunner, env) -> None:
    r = runner.invoke(app, [], env=None)
    assert r.exit_code == 0
    assert "not an interactive terminal" in r.output
    assert "sobai ask" in r.output


def test_json_no_subcommand_errors(runner: CliRunner, env) -> None:
    r = runner.invoke(app, ["--json"], env=None)
    assert r.exit_code != 0
    assert isinstance(r.exception, SobaiError)


def test_help_and_version_do_not_launch(
    runner: CliRunner, env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_app):  # type: ignore[no-untyped-def]
        raise AssertionError("session must not launch for --help/--version")

    monkeypatch.setattr(session_mod, "launch_or_guide", _boom)
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["--version"]).exit_code == 0


def test_tty_dispatch_launches(runner: CliRunner, env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sobai.ui.console.UI.stdin_is_tty", lambda self: True)
    monkeypatch.setattr("sobai.ui.console.UI.stdout_is_tty", lambda self: True)
    called = {"n": 0}
    monkeypatch.setattr(InteractiveSession, "welcome", lambda self: None)
    monkeypatch.setattr(
        InteractiveSession, "run", lambda self, reader=None: called.__setitem__("n", 1)
    )
    r = runner.invoke(app, [], env=None)
    assert r.exit_code == 0
    assert called["n"] == 1


# --------------------------------------------------------------------------- #
# welcome screen
# --------------------------------------------------------------------------- #
def test_welcome_content_and_no_secrets(env, capsys) -> None:
    app_ctx = make_app(provider="ollama", model="ollama:qwen2.5-coder:7b")
    InteractiveSession(app_ctx).welcome()
    out = capsys.readouterr().out
    assert "SoBatista AI" in out
    assert "One CLI. Any model. Your tools." in out
    assert "0.1.0.dev0" in out
    assert "ollama" in out and "local" in out
    assert "local-only" in out
    assert "/help" in out
    # no identity / paths / secrets
    assert "@" not in out  # no email
    assert "/config" not in out and str(app_ctx.paths.config_dir) not in out
    assert "token" not in out.lower()


def test_welcome_quiet_minimal(env, capsys) -> None:
    app_ctx = make_app(provider="ollama", model="ollama:x", quiet=True)
    InteractiveSession(app_ctx).welcome()
    out = capsys.readouterr().out
    assert "SoBatista AI" in out
    assert "One CLI. Any model" not in out  # quiet suppresses the full banner


def test_welcome_no_color_has_no_ansi(env, capsys) -> None:
    app_ctx = make_app(provider="ollama", model="ollama:x", no_color=True)
    InteractiveSession(app_ctx).welcome()
    assert "\x1b[" not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# conversation
# --------------------------------------------------------------------------- #
def test_multi_turn_ordering(env, monkeypatch) -> None:
    provider = FakeProvider(text="ok")
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: provider)
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["hello", "again", EOFError]))
    roles = [m.role for m in s.messages]
    assert [str(r) for r in roles] == ["user", "assistant", "user", "assistant"]
    assert s.messages[0].text() == "hello"
    assert s.turns == 2


def test_context_bound(env, monkeypatch) -> None:
    monkeypatch.setattr(session_mod, "MAX_CONTEXT_MESSAGES", 4)
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: FakeProvider(text="r"))
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["a", "b", "c", "d", EOFError]))
    assert len(s.messages) <= 4


def test_clear_clears_context(env, monkeypatch) -> None:
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: FakeProvider())
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["hello", "/clear", EOFError]))
    assert s.messages == []


def test_empty_input_ignored(env, monkeypatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: provider)
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["", "   ", "hello", EOFError]))
    assert provider.calls == 1  # only the real message was sent


def test_unknown_slash_not_sent_to_model(env, monkeypatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: provider)
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["/bogus", EOFError]))
    assert provider.calls == 0
    assert s.messages == []


def test_exit_and_quit(env) -> None:
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    assert s.handle_slash("/exit") is False
    assert s.handle_slash("/quit") is False
    assert s.handle_slash("/help") is True


def test_eof_exits_cleanly(env) -> None:
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from([EOFError]))  # returns without error


def test_ctrl_c_idle_twice_exits(env) -> None:
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    # two consecutive Ctrl-C at idle prompt → exit
    s.run(reader_from([KeyboardInterrupt, KeyboardInterrupt]))


def test_ctrl_c_during_generation_keeps_state(env, monkeypatch) -> None:
    provider = FakeProvider(fail=KeyboardInterrupt())
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: provider)
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["hello", EOFError]))
    assert s.messages == []  # cancelled generation leaves state clean


def test_provider_error_recovery(env, monkeypatch) -> None:
    good = FakeProvider(text="recovered")
    seq = [FakeProvider(fail=ProviderError("boom")), good]
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: seq.pop(0))
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["first", "second", EOFError]))
    # first errored (nothing committed), second succeeded
    assert [m.text() for m in s.messages] == ["second", "recovered"]


def test_streaming_and_oneshot(env, monkeypatch, capsys) -> None:
    # streaming provider emits deltas
    monkeypatch.setattr(
        session_mod,
        "build_provider",
        lambda *a, **k: FakeProvider(text="hello", chunks=["hel", "lo"]),
    )
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["hi", EOFError]))
    assert "hello" in capsys.readouterr().out
    # one-shot provider streams no deltas but returns text
    monkeypatch.setattr(
        session_mod,
        "build_provider",
        lambda *a, **k: FakeProvider(text="oneshot", stream_deltas=False),
    )
    s2 = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s2.run(reader_from(["hi", EOFError]))
    assert "oneshot" in capsys.readouterr().out


def test_usage_accounting_per_turn(env, monkeypatch) -> None:
    monkeypatch.setattr(
        session_mod,
        "build_provider",
        lambda *a, **k: FakeProvider(usage=Usage(input_tokens=3, output_tokens=4)),
    )
    app_ctx = make_app(provider="ollama", model="ollama:x")
    s = InteractiveSession(app_ctx)
    s.run(reader_from(["a", "b", EOFError]))
    assert s.usage_total.input_tokens == 6
    runs = app_ctx.db.list_runs()
    assert len([r for r in runs if r["command"] == "session"]) == 2
    assert runs[0]["auth_mode"] == "local"


def test_local_only_blocks_cloud(env, monkeypatch) -> None:
    provider = FakeProvider(name="anthropic")
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: provider)
    s = InteractiveSession(make_app(provider="anthropic", model="anthropic:x", local_only=True))
    with pytest.raises(LocalOnlyViolation):
        # send() surfaces the violation; run() would swallow it back to the prompt.
        import asyncio

        asyncio.run(s.send("hi"))
    assert provider.calls == 0  # never attempted the cloud provider
    assert s.messages == []


def test_no_provider_fallback(env, monkeypatch) -> None:
    attempted: list[str] = []

    def _build(name, *a, **k):  # type: ignore[no-untyped-def]
        attempted.append(name)
        raise ProviderUnavailableError(f"{name} unavailable")

    monkeypatch.setattr(session_mod, "build_provider", _build)
    s = InteractiveSession(make_app(provider="claude-cli", model="default"))
    s.run(reader_from(["hi", EOFError]))
    assert attempted == ["claude-cli"]  # no switch to another provider
    assert s.messages == []


def test_no_tools_enabled(env, monkeypatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: provider)
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["hi", EOFError]))
    assert provider.last_params is not None
    assert provider.last_params.tools == []  # connectors/tools never auto-enabled


def test_malicious_unicode_sanitized(env, monkeypatch, capsys) -> None:
    evil = "A\x1b[31mRED\x1b]0;title\x07‮REVERSED‬\x00B"
    monkeypatch.setattr(
        session_mod, "build_provider", lambda *a, **k: FakeProvider(text=evil, chunks=[evil])
    )
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.run(reader_from(["hi", EOFError]))
    out = capsys.readouterr().out
    assert "\x1b[31m" not in out and "\x1b]0;" not in out
    assert "‮" not in out and "‬" not in out
    assert "\x00" not in out


def test_provider_switch_session_only(env, monkeypatch) -> None:
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    s.handle_slash("/provider claude")
    assert s.provider == "anthropic"  # canonicalized, session override
    # persistent config is untouched
    assert s.app.config.config.active_provider is None


def test_unknown_provider_switch_errors(env) -> None:
    s = InteractiveSession(make_app(provider="ollama", model="ollama:x"))
    assert s.handle_slash("/provider nope") is True  # stays in session
    assert s.provider == "ollama"  # unchanged
