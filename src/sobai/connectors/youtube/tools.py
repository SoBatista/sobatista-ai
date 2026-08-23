"""Typed, read-only YouTube tools exposed to models via the orchestrator.

These are the deterministic foundation behind `sobai youtube ask`: each tool has
a JSON-Schema contract, returns observed data with provenance as a JSON string,
never writes, and classifies its data as INTERNAL so the egress policy applies
before results reach a cloud model.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from sobai.core.classification import DataClass
from sobai.tools import Tool, ToolRegistry

from . import analytics
from .client import YouTubeClient
from .period import DateRange, resolve_range

_DATE_ARGS: dict[str, Any] = {
    "period": {"type": "string", "description": "Relative window, e.g. 30d, 12w, 3m."},
    "start": {"type": "string", "description": "Explicit start date YYYY-MM-DD."},
    "end": {"type": "string", "description": "Explicit end date YYYY-MM-DD."},
}


class _YouTubeTool(Tool):
    writes = False
    data_class = DataClass.INTERNAL

    def __init__(self, client: YouTubeClient, *, monetary_granted: bool) -> None:
        self._client = client
        self._monetary = monetary_granted

    def _range(self, args: dict[str, Any]) -> DateRange:
        return resolve_range(
            period=args.get("period"), start=args.get("start"), end=args.get("end")
        )

    @staticmethod
    def _dump(payload: Any) -> str:
        return json.dumps(payload, default=str, ensure_ascii=False)


class ChannelTool(_YouTubeTool):
    name = "youtube_channel"
    description = "Get the authorized channel's snippet and lifetime statistics."
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def run(self, arguments: dict[str, Any]) -> str:
        channel = await self._client.get_channel()
        snippet = channel.get("snippet", {})
        stats = channel.get("statistics", {})
        return self._dump(
            {
                "source": {"api": "youtube.data.v3", "endpoint": "channels.list"},
                "observed": {
                    "id": channel.get("id"),
                    "title": snippet.get("title"),
                    "published_at": snippet.get("publishedAt"),
                    "country": snippet.get("country"),
                    "statistics": stats,
                },
            }
        )


class AnalyticsSummaryTool(_YouTubeTool):
    name = "youtube_analytics_summary"
    description = "Aggregate channel analytics totals for a date range."
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": dict(_DATE_ARGS)}

    async def run(self, arguments: dict[str, Any]) -> str:
        report = await analytics.summary_report(
            self._client, self._range(arguments), monetary_granted=self._monetary
        )
        return self._dump(report.to_dict())


class TopVideosTool(_YouTubeTool):
    name = "youtube_top_videos"
    description = "Top videos by a metric (views or watch-time) for a date range."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            **_DATE_ARGS,
            "metric": {"type": "string", "enum": ["views", "watch-time"], "default": "views"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 10},
        },
    }

    async def run(self, arguments: dict[str, Any]) -> str:
        report = await analytics.top_videos_report(
            self._client,
            self._range(arguments),
            metric=arguments.get("metric", "views"),
            limit=int(arguments.get("limit", 10)),
        )
        return self._dump(report.to_dict())


class TrafficSourcesTool(_YouTubeTool):
    name = "youtube_traffic_sources"
    description = "Traffic source breakdown for a date range."
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": dict(_DATE_ARGS)}

    async def run(self, arguments: dict[str, Any]) -> str:
        report = await analytics.traffic_sources_report(self._client, self._range(arguments))
        return self._dump(report.to_dict())


class GeographyTool(_YouTubeTool):
    name = "youtube_geography"
    description = "Views/watch-time by country for a date range."
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": dict(_DATE_ARGS)}

    async def run(self, arguments: dict[str, Any]) -> str:
        report = await analytics.geography_report(self._client, self._range(arguments))
        return self._dump(report.to_dict())


class DeviceTool(_YouTubeTool):
    name = "youtube_device_types"
    description = "Views/watch-time by device type for a date range."
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": dict(_DATE_ARGS)}

    async def run(self, arguments: dict[str, Any]) -> str:
        report = await analytics.device_report(self._client, self._range(arguments))
        return self._dump(report.to_dict())


class VideoStatsTool(_YouTubeTool):
    name = "youtube_video_stats"
    description = "Analytics for a single video over a date range."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {**_DATE_ARGS, "video_id": {"type": "string"}},
        "required": ["video_id"],
    }

    async def run(self, arguments: dict[str, Any]) -> str:
        report = await analytics.video_report(
            self._client,
            self._range(arguments),
            video_id=arguments["video_id"],
            monetary_granted=self._monetary,
        )
        return self._dump(report.to_dict())


def build_registry(client: YouTubeClient, *, monetary_granted: bool) -> ToolRegistry:
    registry = ToolRegistry()
    for cls in (
        ChannelTool,
        AnalyticsSummaryTool,
        TopVideosTool,
        TrafficSourcesTool,
        GeographyTool,
        DeviceTool,
        VideoStatsTool,
    ):
        registry.register(cls(client, monetary_granted=monetary_granted))
    return registry
