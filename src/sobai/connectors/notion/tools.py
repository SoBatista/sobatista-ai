"""Typed, read-only Notion tools exposed to models via the orchestrator.

The deterministic foundation behind `sobai notion ask`: each tool has a
JSON-Schema contract, returns observed data with source provenance as a JSON
string, never writes, and is classified INTERNAL so the egress policy applies
before any result reaches a cloud model.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from sobai.core.classification import DataClass
from sobai.tools import Tool, ToolRegistry

from . import retrieval
from .client import NotionClient


class _NotionTool(Tool):
    writes = False
    data_class = DataClass.INTERNAL

    def __init__(self, client: NotionClient) -> None:
        self._client = client

    @staticmethod
    def _dump(payload: Any) -> str:
        return json.dumps(payload, default=str, ensure_ascii=False)


class SearchTool(_NotionTool):
    name = "notion_search"
    description = "Search pages and data sources shared with the integration (by title)."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Title search term (optional)."},
            "object_type": {"type": "string", "enum": ["page", "data_source"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        },
    }

    async def run(self, arguments: dict[str, Any]) -> str:
        results = await retrieval.search_pages(
            self._client,
            arguments.get("query"),
            object_type=arguments.get("object_type"),
            limit=int(arguments.get("limit", 25)),
        )
        return self._dump(
            {"source": {"api": "notion.v1", "endpoint": "search"}, "observed": results}
        )


class RecentTool(_NotionTool):
    name = "notion_recent"
    description = "List pages edited within a recent window (e.g. 7d)."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "since": {
                "type": "string",
                "description": "Window, e.g. 7d, 24h, 4w.",
                "default": "7d",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
        },
    }

    async def run(self, arguments: dict[str, Any]) -> str:
        results = await retrieval.recent_pages(
            self._client, since=arguments.get("since", "7d"), limit=int(arguments.get("limit", 50))
        )
        return self._dump(
            {
                "source": {"api": "notion.v1", "endpoint": "search"},
                "observed": results,
                "window": arguments.get("since", "7d"),
            }
        )


class ReadPageTool(_NotionTool):
    name = "notion_read_page"
    description = "Read a page's supported block content by id or notion.so URL."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"page": {"type": "string", "description": "Page id or notion.so URL."}},
        "required": ["page"],
    }

    async def run(self, arguments: dict[str, Any]) -> str:
        page = await retrieval.read_page(self._client, arguments["page"])
        return self._dump(page)


class ProjectsTool(_NotionTool):
    name = "notion_projects"
    description = "Heuristic list of project-like pages/data sources (not authoritative)."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}},
    }

    async def run(self, arguments: dict[str, Any]) -> str:
        candidates, notes = await retrieval.project_candidates(
            self._client, limit=int(arguments.get("limit", 25))
        )
        return self._dump({"observed": candidates, "notes": notes})


def build_registry(client: NotionClient) -> ToolRegistry:
    registry = ToolRegistry()
    for cls in (SearchTool, RecentTool, ReadPageTool, ProjectsTool):
        registry.register(cls(client))
    return registry
