"""Higher-level YouTube Analytics reports with feature-detection and provenance.

Builds only metric/dimension combinations documented as valid, and degrades
gracefully (a note, never fabricated numbers) when the API rejects a query or
when a requested metric is not exposed by the public API at all.
"""

from __future__ import annotations

from typing import Any

from .client import UnsupportedQueryError, YouTubeClient
from .period import DateRange
from .reports import Report, ReportMeta, SourceMeta

ANALYTICS_API = "youtubeAnalytics.v2"
ENDPOINT = "reports.query"

# Core, non-monetary metrics safe to aggregate without dimensions.
SUMMARY_METRICS = [
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "dislikes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
]

# Revenue metrics — only queried when the monetary scope was granted.
MONETARY_METRICS = [
    "estimatedRevenue",
    "estimatedAdRevenue",
    "grossRevenue",
    "cpm",
    "monetizedPlaybacks",
    "playbackBasedCpm",
]

# Metrics people expect but which the public Analytics API does NOT expose.
STUDIO_ONLY_NOTE = (
    "Thumbnail impressions and impression click-through rate are not available in "
    "the public YouTube Analytics API (YouTube Studio only); they are omitted, not "
    "estimated."
)
NEW_RETURNING_NOTE = (
    "A new-vs-returning viewer breakdown is not available via the YouTube Analytics "
    "API; it is omitted, not estimated."
)
MONETARY_NOT_GRANTED_NOTE = (
    "Revenue metrics were not requested: the monetary scope is not granted. Re-run "
    "`sobai connect youtube --monetary` to include them."
)

# Friendly `top --metric` names -> API metric names.
TOP_METRIC_MAP = {
    "views": "views",
    "watch-time": "estimatedMinutesWatched",
    "watch_time": "estimatedMinutesWatched",
    "watchtime": "estimatedMinutesWatched",
    "subscribers": "subscribersGained",
    "likes": "likes",
    "comments": "comments",
}

MAX_TOP_RESULTS = 200  # API-enforced ceiling for dimensions=video


def rows_to_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Zip columnHeaders with rows into a list of dicts."""
    headers = [h.get("name") for h in result.get("columnHeaders", [])]
    return [dict(zip(headers, row, strict=False)) for row in result.get("rows", [])]


def _meta(
    report: str,
    drange: DateRange,
    *,
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: str | None = None,
    sort: str | None = None,
    comparison: dict[str, Any] | None = None,
) -> ReportMeta:
    return ReportMeta(
        report=report,
        date_range=drange.as_iso(),
        comparison=comparison,
        source=SourceMeta(
            api=ANALYTICS_API,
            endpoint=ENDPOINT,
            ids="channel==MINE",
            metrics=metrics,
            dimensions=dimensions or [],
            filters=filters,
            sort=sort,
        ),
    )


async def summary_report(
    client: YouTubeClient, drange: DateRange, *, monetary_granted: bool
) -> Report:
    metrics = list(SUMMARY_METRICS)
    notes = [STUDIO_ONLY_NOTE, NEW_RETURNING_NOTE]
    if monetary_granted:
        metrics = metrics + MONETARY_METRICS
    else:
        notes.append(MONETARY_NOT_GRANTED_NOTE)
    result = await client.query_analytics(
        start=drange.start.isoformat(), end=drange.end.isoformat(), metrics=metrics
    )
    dicts = rows_to_dicts(result)
    observed = dicts[0] if dicts else dict.fromkeys(metrics, 0)
    return Report(
        meta=_meta("analytics.summary", drange, metrics=metrics), observed=observed, notes=notes
    )


async def compare_report(
    client: YouTubeClient,
    current: DateRange,
    previous: DateRange,
    *,
    monetary_granted: bool,
) -> Report:
    cur = await summary_report(client, current, monetary_granted=monetary_granted)
    prev = await summary_report(client, previous, monetary_granted=monetary_granted)
    deltas: dict[str, Any] = {}
    for key, cur_val in cur.observed.items():
        prev_val = prev.observed.get(key)
        try:
            c = float(cur_val)
            p = float(prev_val)
            deltas[key] = {
                "current": cur_val,
                "previous": prev_val,
                "delta": round(c - p, 4),
                "pct_change": round((c - p) / p * 100, 2) if p else None,
            }
        except (TypeError, ValueError):
            deltas[key] = {"current": cur_val, "previous": prev_val}
    meta = _meta(
        "analytics.compare",
        current,
        metrics=list(cur.observed.keys()),
        comparison={"previous_range": previous.as_iso()},
    )
    return Report(meta=meta, observed=deltas, notes=cur.notes)


async def top_videos_report(
    client: YouTubeClient, drange: DateRange, *, metric: str, limit: int
) -> Report:
    api_metric = TOP_METRIC_MAP.get(metric.lower())
    if api_metric is None:
        raise UnsupportedQueryError(
            f"Unknown top metric '{metric}'.",
            hint=f"Choose one of: {', '.join(sorted(set(TOP_METRIC_MAP)))}.",
        )
    limit = max(1, min(limit, MAX_TOP_RESULTS))
    metrics = sorted({api_metric, "views", "estimatedMinutesWatched"})
    sort = f"-{api_metric}"
    result = await client.query_analytics(
        start=drange.start.isoformat(),
        end=drange.end.isoformat(),
        metrics=metrics,
        dimensions=["video"],
        sort=sort,
        max_results=limit,
    )
    rows = rows_to_dicts(result)
    video_ids = [str(r["video"]) for r in rows if r.get("video")]
    titles: dict[str, str] = {}
    if video_ids:
        for item in await client.list_videos(video_ids):
            titles[item["id"]] = item.get("snippet", {}).get("title", "")
    observed = []
    for rank, row in enumerate(rows, start=1):
        vid = row.get("video", "")
        observed.append(
            {
                "rank": rank,
                "video_id": vid,
                "title": titles.get(vid, ""),
                **{m: row.get(m) for m in metrics},
            }
        )
    meta = _meta(
        "analytics.top",
        drange,
        metrics=metrics,
        dimensions=["video"],
        sort=sort,
    )
    return Report(meta=meta, observed=observed, notes=[f"Sorted by {api_metric}, limit {limit}."])


async def _dimension_report(
    client: YouTubeClient,
    drange: DateRange,
    *,
    report_name: str,
    dimension: str,
    metrics: list[str] | None = None,
    sort: str | None = None,
    max_results: int | None = None,
) -> Report:
    metrics = metrics or ["views", "estimatedMinutesWatched"]
    meta = _meta(report_name, drange, metrics=metrics, dimensions=[dimension], sort=sort)
    try:
        result = await client.query_analytics(
            start=drange.start.isoformat(),
            end=drange.end.isoformat(),
            metrics=metrics,
            dimensions=[dimension],
            sort=sort,
            max_results=max_results,
        )
    except UnsupportedQueryError as exc:
        return Report(
            meta=meta,
            observed=[],
            notes=[f"Not available: {exc.message}"],
        )
    return Report(meta=meta, observed=rows_to_dicts(result))


async def traffic_sources_report(client: YouTubeClient, drange: DateRange) -> Report:
    return await _dimension_report(
        client,
        drange,
        report_name="analytics.traffic_sources",
        dimension="insightTrafficSourceType",
        sort="-views",
    )


async def geography_report(client: YouTubeClient, drange: DateRange, *, limit: int = 25) -> Report:
    return await _dimension_report(
        client,
        drange,
        report_name="analytics.geography",
        dimension="country",
        sort="-views",
        max_results=limit,
    )


async def device_report(client: YouTubeClient, drange: DateRange) -> Report:
    return await _dimension_report(
        client,
        drange,
        report_name="analytics.device_types",
        dimension="deviceType",
        sort="-views",
    )


async def video_report(
    client: YouTubeClient, drange: DateRange, *, video_id: str, monetary_granted: bool
) -> Report:
    metrics = list(SUMMARY_METRICS)
    notes = [STUDIO_ONLY_NOTE]
    if monetary_granted:
        metrics = metrics + MONETARY_METRICS
    else:
        notes.append(MONETARY_NOT_GRANTED_NOTE)
    filters = f"video=={video_id}"
    result = await client.query_analytics(
        start=drange.start.isoformat(),
        end=drange.end.isoformat(),
        metrics=metrics,
        filters=filters,
    )
    dicts = rows_to_dicts(result)
    observed = dicts[0] if dicts else dict.fromkeys(metrics, 0)
    return Report(
        meta=_meta("analytics.video", drange, metrics=metrics, filters=filters),
        observed=observed,
        notes=notes,
    )
