from __future__ import annotations

import json

import httpx
import respx

from sobai.connectors.youtube.client import ANALYTICS_BASE, DATA_BASE, YouTubeClient
from sobai.connectors.youtube.reports import Report, ReportMeta, SourceMeta
from sobai.connectors.youtube.tools import build_registry

REPORTS_URL = f"{ANALYTICS_BASE}/reports"
CHANNELS_URL = f"{DATA_BASE}/channels"


def test_report_separates_observed_and_ai() -> None:
    report = Report(
        meta=ReportMeta(
            report="r",
            date_range={"start": "a", "end": "b"},
            source=SourceMeta(api="x", endpoint="y"),
        ),
        observed={"views": 1},
        ai_interpretation="an opinion",
    )
    d = report.to_dict()
    assert d["observed"] == {"views": 1}
    assert d["ai_interpretation"] == "an opinion"
    assert d["meta"]["timezone"]  # provenance present


def test_registry_is_read_only(yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    registry = build_registry(client, monetary_granted=False)
    names = set(registry.names())
    assert {"youtube_channel", "youtube_analytics_summary", "youtube_top_videos"} <= names
    assert all(not spec.writes for spec in registry.specs(include_writes=True))


async def test_channel_tool_returns_provenance(yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    registry = build_registry(client, monetary_granted=False)
    tool = registry.get("youtube_channel")
    assert tool is not None
    with respx.mock as mock:
        mock.get(CHANNELS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC1",
                            "snippet": {"title": "Chan"},
                            "statistics": {"subscriberCount": "10"},
                        }
                    ]
                },
            )
        )
        out = json.loads(await tool.run({}))
    await client.aclose()
    assert out["source"]["endpoint"] == "channels.list"
    assert out["observed"]["statistics"]["subscriberCount"] == "10"


async def test_summary_tool_json_has_meta(yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    registry = build_registry(client, monetary_granted=False)
    tool = registry.get("youtube_analytics_summary")
    assert tool is not None
    with respx.mock as mock:
        mock.get(REPORTS_URL).mock(
            return_value=httpx.Response(200, json={"columnHeaders": [], "rows": []})
        )
        out = json.loads(await tool.run({"period": "7d"}))
    await client.aclose()
    assert out["meta"]["date_range"]["start"]
    assert "Pacific Time" in out["meta"]["timezone"]
