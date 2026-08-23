"""Tests for `sobai usage` local usage visibility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sobai.cli.app import app
from sobai.core.paths import Paths
from sobai.storage import Database


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    monkeypatch.setenv("SOBAI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SOBAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOBAI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NO_COLOR", "1")
    return Paths.resolve()


def _seed(env: Paths) -> None:
    db = Database(env.state_db)
    db.start_run(
        "r1", "ask", provider="claude-cli", model="provider-default", auth_mode="subscription"
    )
    db.finish_run(
        "r1",
        status="ok",
        exit_code=0,
        input_tokens=100,
        output_tokens=50,
        cached_input_tokens=20,
        cost_usd=0.0123,
        cost_kind="estimated",
        duration_ms=1500,
        tool_rounds=0,
    )
    db.start_run("r2", "ask", provider="ollama", model="qwen", auth_mode="local")
    db.finish_run(
        "r2",
        status="ok",
        exit_code=0,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0,
        cost_kind="actual",
    )
    db.start_run(
        "r3",
        "youtube ask",
        provider="codex-cli",
        model="provider-default",
        auth_mode="subscription",
    )
    db.finish_run(
        "r3", status="ok", exit_code=0, input_tokens=30, output_tokens=8, cost_kind="unavailable"
    )
    db.close()


def test_usage_json(runner: CliRunner, env: Paths) -> None:
    _seed(env)
    result = runner.invoke(app, ["--json", "usage"], env=None)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)  # JSON output must be clean/parseable
    by_provider = {r["provider"]: r for r in data["rows"]}
    assert by_provider["claude-cli"]["cost_usd"] == pytest.approx(0.0123)
    assert by_provider["claude-cli"]["auth_mode"] == "subscription"
    assert by_provider["codex-cli"]["cost_usd"] is None  # subscription, no cost invented
    assert by_provider["ollama"]["auth_mode"] == "local"
    assert by_provider["claude-cli"]["duration_ms"] == 1500
    assert "tool_rounds" in by_provider["claude-cli"]
    assert data["notes"]


def test_usage_text_shows_modes(runner: CliRunner, env: Paths) -> None:
    _seed(env)
    result = runner.invoke(app, ["usage"], env=None)
    assert result.exit_code == 0
    assert "subscription" in result.output
    assert "local" in result.output
    assert "estimate" in result.output.lower()


def test_usage_provider_filter(runner: CliRunner, env: Paths) -> None:
    _seed(env)
    result = runner.invoke(app, ["--json", "usage", "--provider", "codex-cli"], env=None)
    data = json.loads(result.output)
    assert {r["provider"] for r in data["rows"]} == {"codex-cli"}


def test_usage_empty(runner: CliRunner, env: Paths) -> None:
    result = runner.invoke(app, ["usage"], env=None)
    assert result.exit_code == 0
    assert "No usage" in result.output
