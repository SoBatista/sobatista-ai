from __future__ import annotations

import httpx
import respx

from sobai.connectors.youtube import analytics as yta
from sobai.connectors.youtube.client import ANALYTICS_BASE, DATA_BASE, YouTubeClient
from sobai.connectors.youtube.period import resolve_range

REPORTS_URL = f"{ANALYTICS_BASE}/reports"
VIDEOS_URL = f"{DATA_BASE}/videos"
DRANGE = resolve_range(period="30d")


def test_rows_to_dicts() -> None:
    result = {
        "columnHeaders": [{"name": "day"}, {"name": "views"}],
        "rows": [["2026-01-01", 10], ["2026-01-02", 20]],
    }
    assert yta.rows_to_dicts(result) == [
        {"day": "2026-01-01", "views": 10},
        {"day": "2026-01-02", "views": 20},
    ]


async def test_summary_report_provenance_and_notes(yt_auth) -> None:
    client = YouTubeClient(yt_auth(monetary=False))
    row = [100, 5000, 120.0, 45.0, 10, 1, 3, 2, 7, 1]
    headers = [{"name": m} for m in yta.SUMMARY_METRICS]
    with respx.mock as mock:
        mock.get(REPORTS_URL).mock(
            return_value=httpx.Response(200, json={"columnHeaders": headers, "rows": [row]})
        )
        report = await yta.summary_report(client, DRANGE, monetary_granted=False)
    await client.aclose()
    assert report.observed["views"] == 100
    # provenance present
    meta = report.meta.to_dict()
    assert meta["date_range"]["start"] == DRANGE.start.isoformat()
    assert "Pacific Time" in meta["timezone"]
    assert meta["freshness"]
    assert meta["source"]["metrics"][0] == "views"
    # honest omissions
    assert any("impression" in n.lower() for n in report.notes)
    assert any(
        "new-vs-returning" in n.lower() or "new vs returning" in n.lower() for n in report.notes
    )
    assert any("monetary" in n.lower() for n in report.notes)


async def test_summary_includes_monetary_when_granted(yt_auth) -> None:
    client = YouTubeClient(yt_auth(monetary=True))
    with respx.mock as mock:
        route = mock.get(REPORTS_URL).mock(
            return_value=httpx.Response(200, json={"columnHeaders": [], "rows": []})
        )
        report = await yta.summary_report(client, DRANGE, monetary_granted=True)
    await client.aclose()
    assert "estimatedRevenue" in route.calls.last.request.url.params["metrics"]
    assert not any("monetary" in n.lower() for n in report.notes)


async def test_top_videos_merges_titles_and_sorts(yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    analytics_json = {
        "columnHeaders": [
            {"name": "video"},
            {"name": "estimatedMinutesWatched"},
            {"name": "views"},
        ],
        "rows": [["vidAAAAAAAA1", 900, 300], ["vidBBBBBBBB2", 500, 200]],
    }
    videos_json = {
        "items": [
            {"id": "vidAAAAAAAA1", "snippet": {"title": "First"}},
            {"id": "vidBBBBBBBB2", "snippet": {"title": "Second"}},
        ]
    }
    with respx.mock as mock:
        route = mock.get(REPORTS_URL).mock(return_value=httpx.Response(200, json=analytics_json))
        mock.get(VIDEOS_URL).mock(return_value=httpx.Response(200, json=videos_json))
        report = await yta.top_videos_report(client, DRANGE, metric="watch-time", limit=2)
    await client.aclose()
    assert report.meta.source.sort == "-estimatedMinutesWatched"
    assert route.calls.last.request.url.params["dimensions"] == "video"
    assert report.observed[0]["title"] == "First"
    assert report.observed[0]["rank"] == 1


async def test_dimension_report_degrades_on_unsupported(yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    with respx.mock as mock:
        mock.get(REPORTS_URL).mock(
            return_value=httpx.Response(
                400, json={"error": {"message": "nope", "errors": [{"reason": "badRequest"}]}}
            )
        )
        report = await yta.traffic_sources_report(client, DRANGE)
    await client.aclose()
    assert report.observed == []
    assert any("not available" in n.lower() for n in report.notes)


async def test_top_unknown_metric_rejected(yt_auth) -> None:
    import pytest

    from sobai.connectors.youtube.client import UnsupportedQueryError

    client = YouTubeClient(yt_auth())
    with pytest.raises(UnsupportedQueryError):
        await yta.top_videos_report(client, DRANGE, metric="bogus", limit=5)
    await client.aclose()
