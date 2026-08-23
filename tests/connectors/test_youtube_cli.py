from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sobai.cli import youtube_cmd
from sobai.cli.app import app
from sobai.connectors.youtube import analytics as yta
from sobai.connectors.youtube.oauth import TokenBundle, YouTubeAuth
from sobai.connectors.youtube.reports import Report, ReportMeta, SourceMeta
from sobai.core.errors import ConnectorError, LocalOnlyViolation, PolicyError
from sobai.core.types import Completion, GenerateParams, StopReason, StreamEvent, Usage
from sobai.providers.base import Provider, ProviderHealth
from sobai.tools import ToolRegistry


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
    }


class FakeConnector:
    def __init__(self, *args: Any, connected: bool = True, **kwargs: Any) -> None:
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected

    def monetary_granted(self) -> bool:
        return False

    def captions_granted(self) -> bool:
        return False

    def client(self) -> Any:
        return object()

    def tools(self) -> ToolRegistry:
        return ToolRegistry()

    async def aclose(self) -> None:
        return None


class FakeProvider(Provider):
    name = "ollama"
    is_local = True

    async def generate(self, params: GenerateParams) -> Completion:
        return Completion(text="grounded answer", stop_reason=StopReason.END_TURN, usage=Usage())

    async def stream(
        self, params: GenerateParams
    ) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        from sobai.core.types import StreamEventType

        yield StreamEvent(type=StreamEventType.DONE, completion=await self.generate(params))

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


def _report(observed: Any, name: str = "analytics.summary") -> Report:
    return Report(
        meta=ReportMeta(
            report=name,
            date_range={"start": "2026-07-25", "end": "2026-08-23"},
            source=SourceMeta(
                api="youtubeAnalytics.v2", endpoint="reports.query", metrics=["views"]
            ),
        ),
        observed=observed,
    )


def test_channel_not_connected(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["youtube", "channel"], env=env)
    assert result.exit_code != 0
    assert isinstance(result.exception, ConnectorError)


def test_analytics_json_has_provenance(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube_cmd, "YouTubeConnector", FakeConnector)

    async def fake_summary(client, drange, *, monetary_granted):  # type: ignore[no-untyped-def]
        return _report({"views": 100, "estimatedMinutesWatched": 5000})

    async def fake_dim(client, drange, **kw):  # type: ignore[no-untyped-def]
        return _report([], name="analytics.traffic_sources")

    monkeypatch.setattr(yta, "summary_report", fake_summary)
    monkeypatch.setattr(yta, "traffic_sources_report", fake_dim)
    monkeypatch.setattr(yta, "geography_report", fake_dim)
    monkeypatch.setattr(yta, "device_report", fake_dim)

    result = runner.invoke(app, ["--json", "youtube", "analytics", "--period", "30d"], env=env)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    meta = data["summary"]["meta"]
    assert meta["date_range"]["start"] == "2026-07-25"
    assert "Pacific Time" in meta["timezone"]
    assert meta["freshness"]
    assert meta["source"]["api"] == "youtubeAnalytics.v2"


def test_top_sanitizes_untrusted_title(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube_cmd, "YouTubeConnector", FakeConnector)

    async def fake_top(client, drange, *, metric, limit):  # type: ignore[no-untyped-def]
        return _report(
            [{"rank": 1, "video_id": "v", "title": "\x1b[31mEVIL\x1b]0;pwn\x07", "views": 5}],
            name="analytics.top",
        )

    monkeypatch.setattr(yta, "top_videos_report", fake_top)
    result = runner.invoke(app, ["youtube", "top", "--metric", "views"], env=env)
    assert result.exit_code == 0
    assert "\x1b[31m" not in result.output  # escape stripped
    assert "\x1b]0;" not in result.output
    assert "EVIL" in result.output  # visible text preserved


def test_ask_local_only_blocks_cloud(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube_cmd, "YouTubeConnector", FakeConnector)
    result = runner.invoke(
        app,
        ["--local-only", "-p", "anthropic", "-m", "anthropic:x", "youtube", "ask", "hi"],
        env=env,
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, LocalOnlyViolation)


def test_ask_cloud_requires_egress_consent_noninteractive(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch, mem_keyring
) -> None:
    monkeypatch.setattr(youtube_cmd, "YouTubeConnector", FakeConnector)
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    # Force the provider to be treated as cloud for egress purposes.
    monkeypatch.setattr(youtube_cmd, "is_local_provider", lambda name: False)
    result = runner.invoke(app, ["-p", "openai", "-m", "openai:x", "youtube", "ask", "hi"], env=env)
    assert result.exit_code != 0
    assert isinstance(result.exception, PolicyError)


def test_ask_local_provider_succeeds(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube_cmd, "YouTubeConnector", FakeConnector)
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    result = runner.invoke(
        app,
        ["--json", "-p", "ollama", "-m", "ollama:x", "youtube", "ask", "how am I doing"],
        env=env,
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["answer"] == "grounded answer"
    assert data["provider"] == "ollama"


def test_disconnect_removes_config_and_token(
    runner: CliRunner, env: dict[str, str], mem_keyring
) -> None:
    # Seed a connected state, then disconnect.
    from sobai.auth import CredentialStore

    auth = YouTubeAuth(CredentialStore())
    auth.save_client("cid", "sec")
    auth.save_token(
        TokenBundle(
            access_token="at",
            refresh_token="rt",
            expiry=datetime.now(UTC) + timedelta(hours=1),
            scope="s",
        )
    )
    result = runner.invoke(app, ["disconnect", "youtube"], env=env)
    assert result.exit_code == 0
    assert not YouTubeAuth(CredentialStore()).is_connected()
