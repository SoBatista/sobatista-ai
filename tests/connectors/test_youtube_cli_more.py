from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sobai.cli import youtube_cmd
from sobai.cli.app import app
from sobai.connectors.youtube import analytics as yta
from sobai.connectors.youtube.captions import TranscriptResult
from sobai.connectors.youtube.reports import Report, ReportMeta, SourceMeta
from sobai.core.types import Completion, GenerateParams, StopReason, StreamEvent, Usage
from sobai.providers.base import Provider, ProviderHealth

VID = "dQw4w9WgXcQ"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
    }


class FakeClient:
    async def get_channel(self) -> dict[str, Any]:
        return {
            "id": "UC1",
            "snippet": {"title": "My Channel", "publishedAt": "2020", "country": "US"},
            "statistics": {"subscriberCount": "100", "viewCount": "5000"},
        }

    async def list_videos(self, ids: list[str]) -> list[dict[str, Any]]:
        return [{"id": ids[0], "snippet": {"title": "Vid"}, "statistics": {"viewCount": "9"}}]


class FakeConnector:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def monetary_granted(self) -> bool:
        return False

    def captions_granted(self) -> bool:
        return False

    def client(self) -> FakeClient:
        return FakeClient()

    async def aclose(self) -> None:
        return None


class FakeProvider(Provider):
    name = "ollama"
    is_local = True

    async def generate(self, params: GenerateParams) -> Completion:
        return Completion(text="AI TEXT", stop_reason=StopReason.END_TURN, usage=Usage())

    async def stream(
        self, params: GenerateParams
    ) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        from sobai.core.types import StreamEventType

        yield StreamEvent(type=StreamEventType.DONE, completion=await self.generate(params))

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


def _report(observed: Any, name: str) -> Report:
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


@pytest.fixture(autouse=True)
def _fake_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(youtube_cmd, "YouTubeConnector", FakeConnector)


def test_channel_text(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["youtube", "channel"], env=env)
    assert r.exit_code == 0, r.output
    assert "My Channel" in r.output
    assert "subscriberCount" in r.output


def test_channel_json(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["--json", "youtube", "channel"], env=env)
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["observed"]["id"] == "UC1"


def test_analytics_text_renders_sections(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_summary(client, drange, *, monetary_granted):  # type: ignore[no-untyped-def]
        return _report({"views": 1}, "analytics.summary")

    async def fake_dim(client, drange, **kw):  # type: ignore[no-untyped-def]
        return _report([], "analytics.dim")

    monkeypatch.setattr(yta, "summary_report", fake_summary)
    monkeypatch.setattr(yta, "traffic_sources_report", fake_dim)
    monkeypatch.setattr(yta, "geography_report", fake_dim)
    monkeypatch.setattr(yta, "device_report", fake_dim)
    r = runner.invoke(app, ["youtube", "analytics"], env=env)
    assert r.exit_code == 0, r.output
    assert "Analytics summary" in r.output
    assert "Pacific Time" in r.output
    assert "freshness" in r.output


def test_compare_text(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_compare(client, cur, prev, *, monetary_granted):  # type: ignore[no-untyped-def]
        return _report(
            {"views": {"current": 10, "previous": 5, "delta": 5, "pct_change": 100.0}},
            "analytics.compare",
        )

    monkeypatch.setattr(yta, "compare_report", fake_compare)
    r = runner.invoke(app, ["youtube", "compare", "--period", "30d"], env=env)
    assert r.exit_code == 0, r.output
    assert "views" in r.output


def test_compare_no_previous_errors(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["youtube", "compare", "--no-previous"], env=env)
    assert r.exit_code != 0


def test_video_json(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_video(client, drange, *, video_id, monetary_granted):  # type: ignore[no-untyped-def]
        return _report({"views": 42}, "analytics.video")

    monkeypatch.setattr(yta, "video_report", fake_video)
    r = runner.invoke(app, ["--json", "youtube", "video", VID], env=env)
    assert r.exit_code == 0
    assert json.loads(r.output)["observed"]["views"] == 42


def test_summarize_no_transcript_reports_clearly(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_resolve(client, video_id, *, captions_granted, transcript_path=None):  # type: ignore[no-untyped-def]
        return TranscriptResult(source="none", text=None, detail="No authorized transcript.")

    monkeypatch.setattr(youtube_cmd, "resolve_transcript", fake_resolve)
    r = runner.invoke(app, ["--json", "youtube", "summarize", VID], env=env)
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["ai_interpretation"] is None
    assert data["observed"]["transcript_source"] == "none"


def test_summarize_with_transcript_uses_provider(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_resolve(client, video_id, *, captions_granted, transcript_path=None):  # type: ignore[no-untyped-def]
        return TranscriptResult(source="user-supplied", text="the words", detail="ok")

    monkeypatch.setattr(youtube_cmd, "resolve_transcript", fake_resolve)
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    r = runner.invoke(
        app, ["--json", "-p", "ollama", "-m", "ollama:x", "youtube", "summarize", VID], env=env
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ai_interpretation"] == "AI TEXT"


def test_ideas_uses_provider(
    runner: CliRunner, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_summary(client, drange, *, monetary_granted):  # type: ignore[no-untyped-def]
        return _report({"views": 1}, "analytics.summary")

    async def fake_top(client, drange, *, metric, limit):  # type: ignore[no-untyped-def]
        return _report([], "analytics.top")

    async def fake_traffic(client, drange):  # type: ignore[no-untyped-def]
        return _report([], "analytics.traffic")

    monkeypatch.setattr(yta, "summary_report", fake_summary)
    monkeypatch.setattr(yta, "top_videos_report", fake_top)
    monkeypatch.setattr(yta, "traffic_sources_report", fake_traffic)
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    r = runner.invoke(
        app,
        ["--json", "-p", "ollama", "-m", "ollama:x", "youtube", "ideas", "--period", "90d"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ai_interpretation"] == "AI TEXT"
    assert "summary" in data["observed"]
