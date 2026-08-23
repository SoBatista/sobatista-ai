"""ask records billing mode / cost kind correctly and never falls back."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sobai.cli.app import app
from sobai.cli.common import cost_accounting
from sobai.core.errors import ProviderUnavailableError
from sobai.core.types import Completion, GenerateParams, StopReason, StreamEvent, Usage
from sobai.providers.base import Provider, ProviderHealth


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
    }


class SubscriptionProvider(Provider):
    """Simulates the claude-cli bridge returning a client-estimate cost."""

    name = "claude-cli"
    is_local = False

    async def generate(self, params: GenerateParams) -> Completion:
        return Completion(
            text="hi",
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=3, output_tokens=5, cached_input_tokens=2, cost_usd=0.001),
        )

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        from sobai.core.types import StreamEventType

        yield StreamEvent(type=StreamEventType.DONE, completion=await self.generate(params))

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


def test_cost_accounting_matrix() -> None:
    assert cost_accounting("ollama", Usage()) == ("local", 0.0, "actual")
    assert cost_accounting("claude-cli", Usage(cost_usd=0.01)) == (
        "subscription",
        0.01,
        "estimated",
    )
    assert cost_accounting("codex-cli", Usage()) == ("subscription", None, "unavailable")
    assert cost_accounting("anthropic", Usage()) == ("metered-api", None, "unavailable")


def test_ask_records_subscription_and_estimate(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: SubscriptionProvider())
    r = runner.invoke(app, ["-p", "claude-cli", "-m", "default", "--json", "ask", "hello"], env=env)
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["billing_mode"] == "subscription"
    assert data["cost_kind"] == "estimated"
    assert data["model"] == "provider-default"  # sentinel recorded readably

    hist = json.loads(runner.invoke(app, ["--json", "history"], env=env).output)
    run_id = hist["runs"][0]["id"]
    run = json.loads(runner.invoke(app, ["--json", "runs", "show", run_id], env=env).output)["run"]
    assert run["auth_mode"] == "subscription"
    assert run["cost_kind"] == "estimated"
    assert run["model"] == "provider-default"
    assert run["cached_input_tokens"] == 2
    assert run["tool_rounds"] == 0  # plain ask uses no tools
    assert run["duration_ms"] is not None  # duration recorded per run


def test_ask_no_fallback_on_unavailable_bridge(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*a: Any, **k: Any) -> Provider:
        raise ProviderUnavailableError("claude-cli: not installed")

    monkeypatch.setattr("sobai.cli.common.build_provider", _boom)
    r = runner.invoke(app, ["-p", "claude-cli", "-m", "default", "ask", "hi"], env=env)
    assert r.exit_code != 0
    # It fails cleanly on the chosen provider — never silently switches providers.
    assert isinstance(r.exception, ProviderUnavailableError)
