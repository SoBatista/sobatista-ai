from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sobai.cli.app import app
from sobai.core.errors import LocalOnlyViolation
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
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
    }


class FakeProvider(Provider):
    name = "ollama"
    is_local = True

    def __init__(self, text: str = "fake answer") -> None:
        self._text = text

    async def generate(self, params: GenerateParams) -> Completion:
        return Completion(
            text=self._text,
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=1, output_tokens=2),
            model=params.model,
        )

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type=StreamEventType.TEXT, text=self._text)
        yield StreamEvent(type=StreamEventType.DONE, completion=await self.generate(params))

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


def test_version(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["--version"], env=env)
    assert result.exit_code == 0
    assert "sobai" in result.output


def test_providers_list_json(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["--json", "providers", "list"], env=env)
    assert result.exit_code == 0
    data = json.loads(result.output)
    names = {p["name"] for p in data["providers"]}
    assert {"anthropic", "openai", "ollama"} <= names


def test_model_use_then_list(runner: CliRunner, env: dict[str, str]) -> None:
    r1 = runner.invoke(app, ["model", "use", "ollama:qwen2.5-coder:7b"], env=env)
    assert r1.exit_code == 0
    r2 = runner.invoke(app, ["--json", "models", "list"], env=env)
    data = json.loads(r2.output)
    assert data["active_model"] == "ollama:qwen2.5-coder:7b"


def test_config_show_has_no_secrets(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["config", "show"], env=env)
    assert result.exit_code == 0
    assert "api_key" not in result.output
    assert "providers" in result.output


def test_privacy_explain_json(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["--json", "privacy", "explain"], env=env)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["local_only"] is False
    assert data["egress"]["restricted"] == "deny"


def test_ask_json_with_fake_provider(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider("hi!"))
    result = runner.invoke(
        app, ["-p", "ollama", "-m", "ollama:x", "--json", "ask", "hello"], env=env
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["text"] == "hi!"
    assert data["provider"] == "ollama"
    assert set(data) >= {"run_id", "provider", "model", "text", "stop_reason", "usage"}


def test_ask_records_history(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    runner.invoke(app, ["-p", "ollama", "-m", "ollama:x", "--json", "ask", "q"], env=env)
    result = runner.invoke(app, ["--json", "history"], env=env)
    data = json.loads(result.output)
    assert len(data["runs"]) == 1
    assert data["runs"][0]["command"] == "ask"


def test_ask_local_only_blocks_cloud(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(
        app, ["--local-only", "-p", "anthropic", "-m", "anthropic:x", "ask", "hi"], env=env
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, LocalOnlyViolation)


def test_connect_stores_key(runner: CliRunner, env: dict[str, str], mem_keyring) -> None:
    r = runner.invoke(app, ["connect", "anthropic"], env=env, input="sk-ant-mytestkey123\n")
    assert r.exit_code == 0
    # connections should now report anthropic connected
    r2 = runner.invoke(app, ["--json", "connections"], env=env)
    data = json.loads(r2.output)
    assert data["providers"]["anthropic"] == "connected"


def test_doctor_json(runner: CliRunner, env: dict[str, str], mem_keyring) -> None:
    result = runner.invoke(app, ["--json", "doctor"], env=env)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "keyring" in data
    assert "providers" in data
    assert {p["provider"] for p in data["providers"]} >= {"anthropic", "ollama"}
