"""`sobai ask` renders a model's answer exactly once, however it was delivered.

Providers come in two shapes. A streaming provider emits text deltas and then a
completion repeating the whole answer; a **one-shot** provider — the
``claude-cli`` and ``codex-cli`` bridges, and any endpoint that sends no
``text_delta`` — returns the finished answer having emitted no deltas at all.

Rendering only deltas loses the second kind entirely (the failure these tests
were written for: a successful run that printed nothing). Rendering the
accumulated text unconditionally duplicates the first. Both spellings —
``sobai ask`` and ``sobai run`` — go through the same
:class:`sobai.cli.common.ModelOutput`, so there is one rule, not two.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from sobai.cli.common import ModelOutput
from sobai.core.errors import ExitCode, ProviderError
from sobai.core.types import (
    Completion,
    GenerateParams,
    StopReason,
    StreamEvent,
    StreamEventType,
    Usage,
)
from sobai.providers.base import Provider, ProviderHealth
from sobai.ui.console import UI, OutputMode

Cli = Callable[..., Any]
Query = Callable[[str], list[dict[str, Any]]]

ANSWER = "ZEBRAFISH-ANSWER-TOKEN"


class ShapedProvider(Provider):
    """A provider whose *delivery shape* is the thing under test."""

    is_local = True

    def __init__(
        self,
        *,
        name: str = "ollama",
        text: str = ANSWER,
        deltas: list[str] | None = None,
        interrupt_after: int | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.name = name
        self.is_local = name == "ollama"
        self._text = text
        #: None means "emit no deltas at all" — the one-shot shape.
        self._deltas = deltas
        self._interrupt_after = interrupt_after
        self._fail = fail
        self.generate_calls = 0
        self.stream_calls = 0

    def _completion(self, params: GenerateParams) -> Completion:
        return Completion(
            text=self._text,
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=7, output_tokens=3),
            model=params.model,
        )

    async def generate(self, params: GenerateParams) -> Completion:
        self.generate_calls += 1
        if self._fail:
            raise self._fail
        return self._completion(params)

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        self.stream_calls += 1
        if self._fail:
            raise self._fail
        for index, chunk in enumerate(self._deltas or []):
            if self._interrupt_after is not None and index == self._interrupt_after:
                raise KeyboardInterrupt
            yield StreamEvent(type=StreamEventType.TEXT, text=chunk)
        if self._interrupt_after is not None:
            raise KeyboardInterrupt
        yield StreamEvent(type=StreamEventType.DONE, completion=self._completion(params))

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


@pytest.fixture
def provider_factory(monkeypatch: pytest.MonkeyPatch) -> Callable[..., ShapedProvider]:
    """Install a shaped provider behind `sobai ask`'s provider construction."""

    def _install(**kwargs: Any) -> ShapedProvider:
        provider = ShapedProvider(**kwargs)
        monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: provider)
        return provider

    return _install


def ask(cli: Cli, *args: str, provider: str = "ollama", model: str = "ollama:x") -> Any:
    return cli(["-p", provider, "-m", model, *args])


# --------------------------------------------------------------------------- #
# the shared renderer, in isolation
# --------------------------------------------------------------------------- #
def test_renderer_ignores_empty_deltas() -> None:
    """An empty delta is not output, so it must not suppress the final text."""
    output = ModelOutput(UI(mode=OutputMode.TEXT))
    output.on_text("")
    assert output.streamed is False


def test_renderer_records_a_non_empty_delta() -> None:
    output = ModelOutput(UI(mode=OutputMode.TEXT))
    output.on_text("x")
    assert output.streamed is True


# --------------------------------------------------------------------------- #
# streaming vs one-shot
# --------------------------------------------------------------------------- #
def test_streaming_answer_is_not_printed_twice(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider = provider_factory(deltas=["ZEBRAFISH-", "ANSWER-", "TOKEN"])
    result = ask(cli, "ask", "hello")
    assert result.exit_code == 0, result.output
    assert provider.stream_calls == 1
    assert result.stdout.count(ANSWER) == 1


def test_one_shot_provider_answer_is_printed_once(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    """The regression: deltas never arrive, so the final text has to be rendered."""
    provider_factory(deltas=None)
    result = ask(cli, "ask", "hello")
    assert result.exit_code == 0, result.output
    assert result.stdout.count(ANSWER) == 1


@pytest.mark.parametrize("bridge", ["claude-cli", "codex-cli"])
def test_cli_bridge_one_shot_result_is_rendered(
    cli: Cli, provider_factory: Callable[..., ShapedProvider], bridge: str
) -> None:
    """A subscription bridge returns a finished answer and emits no deltas."""
    provider_factory(name=bridge, deltas=None)
    result = cli(["-p", bridge, "-m", "default", "ask", "hello"])
    assert result.exit_code == 0, result.output
    assert result.stdout.count(ANSWER) == 1


def test_empty_final_response_prints_nothing(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider_factory(text="", deltas=None)
    result = ask(cli, "ask", "hello")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""


def test_no_stream_prints_the_answer_once(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider = provider_factory(deltas=["ZEBRAFISH-", "ANSWER-", "TOKEN"])
    result = ask(cli, "ask", "hello", "--no-stream")
    assert result.exit_code == 0, result.output
    assert provider.stream_calls == 0  # --no-stream really does not stream
    assert provider.generate_calls == 1
    assert result.stdout.count(ANSWER) == 1


# --------------------------------------------------------------------------- #
# output-mode contracts
# --------------------------------------------------------------------------- #
def test_json_mode_is_exactly_one_document(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider_factory(deltas=None)
    result = cli(["-p", "ollama", "-m", "ollama:x", "--json", "ask", "hello"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)  # the whole of stdout is one document
    assert payload["text"] == ANSWER
    assert result.stdout.count(ANSWER) == 1  # no decorative echo alongside it


def test_json_mode_stays_clean_for_a_streaming_provider(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider_factory(deltas=["ZEBRAFISH-", "ANSWER-", "TOKEN"])
    result = cli(["-p", "ollama", "-m", "ollama:x", "--json", "ask", "hello"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["text"] == ANSWER


def test_quiet_suppresses_chatter_but_keeps_the_answer(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider_factory(deltas=None)
    result = cli(["-p", "ollama", "-m", "ollama:x", "--quiet", "ask", "hello"])
    assert result.exit_code == 0, result.output
    assert result.stdout.count(ANSWER) == 1


# --------------------------------------------------------------------------- #
# untrusted output stays untrusted
# --------------------------------------------------------------------------- #
HOSTILE = "Sum\x1b[2Jmary\x1b]0;pwned\x07 and ‮reversed"


def test_one_shot_output_is_sanitized(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider_factory(text=HOSTILE, deltas=None)
    result = ask(cli, "ask", "hello")
    assert result.exit_code == 0, result.output
    assert "\x1b[2J" not in result.stdout
    assert "\x1b]0;" not in result.stdout
    assert "‮" not in result.stdout
    assert "Summary" in result.stdout


def test_streamed_output_is_sanitized(
    cli: Cli, provider_factory: Callable[..., ShapedProvider]
) -> None:
    provider_factory(text=HOSTILE, deltas=[HOSTILE])
    result = ask(cli, "ask", "hello")
    assert result.exit_code == 0, result.output
    assert "\x1b[2J" not in result.stdout
    assert "\x1b]0;" not in result.stdout
    assert "‮" not in result.stdout
    assert result.stdout.count("Summary") == 1


# --------------------------------------------------------------------------- #
# failure paths are unchanged
# --------------------------------------------------------------------------- #
def test_cancellation_exits_130_without_reprinting(
    cli: Cli, provider_factory: Callable[..., ShapedProvider], db_query: Query
) -> None:
    provider_factory(deltas=["partial-", "answer"], interrupt_after=1)
    result = ask(cli, "ask", "hello")
    assert result.exit_code == int(ExitCode.CANCELLED)
    assert result.stdout.count("partial-") == 1
    assert ANSWER not in result.stdout  # a cancelled run never renders a result
    # A cancelled run is left as it was: not marked ok, not rewritten.
    assert db_query("SELECT * FROM runs")[0]["status"] == "running"


def test_provider_error_keeps_its_exit_code_and_marks_the_run(
    cli: Cli, provider_factory: Callable[..., ShapedProvider], db_query: Query
) -> None:
    provider_factory(deltas=None, fail=ProviderError("upstream refused"))
    result = ask(cli, "ask", "hello")
    assert result.exit_code == int(ExitCode.PROVIDER)
    assert "upstream refused" in result.stderr
    assert db_query("SELECT * FROM runs")[0]["status"] == "error"


# --------------------------------------------------------------------------- #
# the real bridges, driven through fake executables (no network, no shell)
# --------------------------------------------------------------------------- #
def _install_fake_claude(bin_dir: Path, answer: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/bash\n"
        'case "$*" in *--help*) echo "--print --output-format --tools --strict-mcp-config '
        "--mcp-config --model --append-system-prompt --safe-mode --disable-slash-commands "
        '--no-session-persistence --setting-sources"; exit 0;; esac\n'
        "cat >/dev/null\n"
        f'echo \'{{"result":"{answer}","usage":{{"input_tokens":3,"output_tokens":5}}}}\'\n'
    )
    script.chmod(0o755)


def _install_fake_codex(bin_dir: Path, answer: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "codex"
    script.write_text(
        "#!/bin/bash\n"
        'case "$*" in *--help*) echo "--json --sandbox --ephemeral --skip-git-repo-check '
        '--cd --ignore-user-config --ignore-rules --config --output-last-message --model"; '
        "exit 0;; esac\n"
        "cat >/dev/null\n"
        f'echo \'{{"type":"item.completed","item":{{"type":"agent_message",'
        f'"text":"{answer}"}}}}\'\n'
        'echo \'{"type":"turn.completed","usage":{"input_tokens":4,"output_tokens":6}}\'\n'
    )
    script.chmod(0o755)


@pytest.mark.parametrize("stream_flag", [[], ["--no-stream"]])
@pytest.mark.parametrize(
    ("bridge", "install"),
    [("claude-cli", _install_fake_claude), ("codex-cli", _install_fake_codex)],
)
def test_mocked_bridge_executable_renders_its_answer_once(
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bridge: str,
    install: Callable[[Path, str], None],
    stream_flag: list[str],
) -> None:
    """End-to-end over the real bridge: one process, one answer, printed once."""
    bin_dir = tmp_path / "bin"
    install(bin_dir, ANSWER)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    result = cli(["-p", bridge, "-m", "default", "ask", *stream_flag, "hello"])
    assert result.exit_code == 0, result.output
    assert result.stdout.count(ANSWER) == 1
