"""The interactive session must not write any prompt-history file to disk."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from sobai.cli import session as session_mod
from sobai.cli.session import InteractiveSession
from sobai.core.context import AppContext, GlobalOptions
from sobai.core.types import Completion, GenerateParams, StreamEvent, StreamEventType, Usage
from sobai.providers.base import Provider, ProviderHealth


class _Fake(Provider):
    name = "ollama"
    is_local = True

    async def generate(self, params: GenerateParams) -> Completion:
        return Completion(text="ok", usage=Usage())

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type=StreamEventType.TEXT, text="ok")
        yield StreamEvent(
            type=StreamEventType.DONE, completion=Completion(text="ok", usage=Usage())
        )

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


def _reader(lines: list[Any]):  # type: ignore[no-untyped-def]
    it = iter(lines)

    def _read(_p: str) -> str:
        try:
            v = next(it)
        except StopIteration:
            raise EOFError from None
        if v is EOFError:
            raise EOFError
        return v

    return _read


def test_no_history_file_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SOBAI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SOBAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOBAI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: _Fake())

    app_ctx = AppContext.build(GlobalOptions(provider="ollama", model="ollama:x"))
    # Use the real default reader path (which imports readline) to prove no file is written.
    session = InteractiveSession(app_ctx)
    session.run(_reader(["hello", "world", EOFError]))
    app_ctx.close()

    # No history-like file anywhere under the sandboxed HOME or app dirs.
    for root in (home, tmp_path / "config", tmp_path / "data", tmp_path / "cache"):
        for p in root.rglob("*"):
            assert "history" not in p.name.lower(), f"unexpected history file: {p}"
