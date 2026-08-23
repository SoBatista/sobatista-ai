from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sobai.cli.app import app
from sobai.core.types import (
    Completion,
    GenerateParams,
    ModelInfo,
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


class StreamingFake(Provider):
    name = "ollama"
    is_local = True

    async def generate(self, params: GenerateParams) -> Completion:
        return Completion(text="streamed text", stop_reason=StopReason.END_TURN, usage=Usage())

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        for chunk in ("stream", "ed ", "text"):
            yield StreamEvent(type=StreamEventType.TEXT, text=chunk)
        yield StreamEvent(type=StreamEventType.DONE, completion=await self.generate(params))

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="qwen2.5-coder:7b", provider="ollama")]

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider="ollama", ok=True, detail="ok")


def test_providers_list_text(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["providers", "list"], env=env)
    assert result.exit_code == 0
    assert "anthropic" in result.output
    assert "ollama" in result.output


def test_profile_lifecycle(runner: CliRunner, env: dict[str, str]) -> None:
    created = runner.invoke(app, ["profile", "create", "creator", "-p", "anthropic"], env=env)
    assert created.exit_code == 0
    r = runner.invoke(app, ["--json", "profile", "list"], env=env)
    data = json.loads(r.output)
    assert "creator" in data["profiles"]
    assert runner.invoke(app, ["profile", "use", "creator"], env=env).exit_code == 0
    r2 = runner.invoke(app, ["--json", "profile", "list"], env=env)
    assert json.loads(r2.output)["active_profile"] == "creator"
    assert runner.invoke(app, ["profile", "delete", "creator"], env=env).exit_code == 0


def test_profile_use_missing(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["profile", "use", "nope"], env=env)
    assert r.exit_code != 0


def test_provider_use(runner: CliRunner, env: dict[str, str]) -> None:
    assert runner.invoke(app, ["provider", "use", "claude"], env=env).exit_code == 0
    r = runner.invoke(app, ["--json", "providers", "list"], env=env)
    assert json.loads(r.output)["active_provider"] == "anthropic"


def test_models_discover(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sobai.cli.providers_cmd.build_provider", lambda *a, **k: StreamingFake())
    r = runner.invoke(app, ["--json", "models", "discover", "-p", "ollama"], env=env)
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["models"][0]["id"] == "qwen2.5-coder:7b"


def test_connections_text(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["connections"], env=env)
    assert r.exit_code == 0
    assert "youtube" in r.output
    assert "notion" in r.output


def test_init_non_interactive(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sobai.cli.init._discover_ollama",
        lambda app: ["qwen2.5-coder:7b", "qwen3-coder:30b"],
    )
    r = runner.invoke(app, ["init"], env=env)
    assert r.exit_code == 0
    cfg = (Path(env["SOBAI_CONFIG_DIR"]) / "config.toml").read_text()
    assert "qwen7b" in cfg
    assert "qwen30b" in cfg


def test_ask_streaming_text(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: StreamingFake())
    r = runner.invoke(app, ["-p", "ollama", "-m", "ollama:x", "ask", "hi"], env=env)
    assert r.exit_code == 0
    assert "streamed text" in r.output


def test_runs_show(runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: StreamingFake())
    runner.invoke(app, ["-p", "ollama", "-m", "ollama:x", "--json", "ask", "hi"], env=env)
    hist = json.loads(runner.invoke(app, ["--json", "history"], env=env).output)
    run_id = hist["runs"][0]["id"]
    r = runner.invoke(app, ["--json", "runs", "show", run_id[:12]], env=env)
    assert r.exit_code == 0
    assert json.loads(r.output)["run"]["command"] == "ask"


def test_update_check_local_only(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["--local-only", "update-check"], env=env)
    assert r.exit_code == 0


def test_tools_list_empty(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["--json", "tools"], env=env)
    assert r.exit_code == 0
    assert json.loads(r.output) == {"tools": []}


def test_disconnect_no_key(runner: CliRunner, env: dict[str, str], mem_keyring) -> None:
    r = runner.invoke(app, ["disconnect", "openai"], env=env)
    assert r.exit_code == 0
