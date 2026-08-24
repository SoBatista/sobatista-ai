"""Fixtures for the Skills suite: on-disk skill factories and a scripted provider."""

from __future__ import annotations

import io
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sobai.cli import app as app_module
from sobai.core.types import (
    Completion,
    GenerateParams,
    StopReason,
    StreamEvent,
    StreamEventType,
    Usage,
)
from sobai.providers.base import Provider, ProviderHealth

MINIMAL_PROMPT = "Summarize the supplied material in three sentences.\n"


def manifest_toml(
    *,
    name: str = "demo",
    version: str = "1.0.0",
    description: str = "A demonstration skill used by the tests.",
    license_: str = "MIT",
    author: str = "SoBatista AI",
    schema_version: int = 1,
    extra: str = "",
) -> str:
    """Render a valid manifest, with room to append or override sections."""
    return f"""schema_version = {schema_version}

[skill]
name = "{name}"
version = "{version}"
description = "{description}"
author = "{author}"
license = "{license_}"
tags = ["testing"]

[input]
description = "Material to work on."
max_bytes = 4096
max_chars = 2048

[output]
format = "markdown"
description = "A short summary."

[policy]
recommended_data_class = "internal"

[provenance]
source = "test fixtures"
created = "2026-08-24"
notes = "Original test content."
{extra}"""


@pytest.fixture
def make_skill_dir(tmp_path: Path) -> Callable[..., Path]:
    """Return a factory that writes a Skill directory and returns its path."""

    def _make(
        name: str = "demo",
        *,
        prompt: str = MINIMAL_PROMPT,
        manifest: str | None = None,
        root: Path | None = None,
        dirname: str | None = None,
        **kwargs: Any,
    ) -> Path:
        base = root if root is not None else tmp_path / "sources"
        base.mkdir(parents=True, exist_ok=True)
        directory = base / (dirname if dirname is not None else name)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "skill.toml").write_text(
            manifest if manifest is not None else manifest_toml(name=name, **kwargs),
            encoding="utf-8",
        )
        (directory / "prompt.md").write_text(prompt, encoding="utf-8")
        return directory

    return _make


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """An empty user Skills directory."""
    directory = tmp_path / "config" / "skills"
    directory.mkdir(parents=True)
    return directory


class ScriptedProvider(Provider):
    """A provider that returns fixed text and records exactly what it was sent."""

    name = "ollama"
    is_local = True

    def __init__(
        self,
        text: str = "scripted answer",
        *,
        usage: Usage | None = None,
        stream_deltas: bool = True,
    ) -> None:
        self.text = text
        self.usage = usage or Usage(input_tokens=11, output_tokens=7)
        self.stream_deltas = stream_deltas
        self.calls: list[GenerateParams] = []
        self.closed = False

    async def generate(self, params: GenerateParams) -> Completion:
        self.calls.append(params)
        return Completion(
            text=self.text,
            stop_reason=StopReason.END_TURN,
            usage=self.usage,
            model=params.model,
        )

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        completion = await self.generate(params)
        if self.stream_deltas and completion.text:
            yield StreamEvent(type=StreamEventType.TEXT, text=completion.text)
        yield StreamEvent(type=StreamEventType.DONE, completion=completion)

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")

    async def aclose(self) -> None:
        self.closed = True

    # -- assertions used by the tests ------------------------------------
    @property
    def system(self) -> str:
        assert self.calls, "provider was never called"
        return self.calls[-1].system or ""

    @property
    def user(self) -> str:
        assert self.calls, "provider was never called"
        return self.calls[-1].messages[-1].text()


class ExplodingProvider(Provider):
    """Fails the test if anything tries to talk to a model."""

    name = "ollama"
    is_local = True

    async def generate(self, params: GenerateParams) -> Completion:
        raise AssertionError("a provider call was made when none was expected")

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        raise AssertionError("a provider stream was opened when none was expected")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    async def list_models(self) -> list[Any]:
        raise AssertionError("model discovery was attempted when none was expected")

    async def health(self) -> ProviderHealth:
        raise AssertionError("a health probe was made when none was expected")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Isolate all app state under tmp_path, in both the mapping and the process."""
    values = {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
        # Rich wraps to the terminal width; keep lines intact so assertions can
        # match digests and paths that would otherwise be split.
        "COLUMNS": "200",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


class FakeStdin:
    """A stdin stand-in that is either a pipe with contents or a terminal."""

    def __init__(self, data: bytes = b"", *, tty: bool = False) -> None:
        self.buffer = io.BytesIO(data)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def read(self) -> str:  # pragma: no cover - only the buffer path is used
        return self.buffer.getvalue().decode()


@dataclass(frozen=True, slots=True)
class CliOutcome:
    """The result of a real `sobai` invocation."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


@pytest.fixture
def cli(
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Callable[..., CliOutcome]:
    """Run the real console entry point, so exit codes and hints are the real ones.

    ``sobai.cli.app.main`` is what a user runs: it catches ``SobaiError``,
    renders the message and hint, and exits with the error's own code. Driving
    it directly (rather than the Typer test runner, which stops at the raised
    exception) is what makes assertions about exit codes meaningful.
    """

    def _run(argv: list[str], *, stdin: bytes | None = None) -> CliOutcome:
        # stdin=None means "a terminal", so an absent input fails fast instead
        # of consuming whatever the test runner happens to have attached.
        monkeypatch.setattr("sys.stdin", FakeStdin(stdin or b"", tty=stdin is None))
        previous = sys.argv
        sys.argv = ["sobai", *argv]
        code = 0
        try:
            app_module.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
        finally:
            sys.argv = previous
        captured = capsys.readouterr()
        return CliOutcome(exit_code=code, stdout=captured.out, stderr=captured.err)

    return _run
