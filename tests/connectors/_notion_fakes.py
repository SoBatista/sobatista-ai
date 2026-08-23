"""Shared fakes for Notion connector tests (not a test module)."""

from __future__ import annotations

from typing import Any

from sobai.connectors.notion.blocks import page_title
from sobai.connectors.notion.client import NotionNotFound


def page(
    pid: str,
    title: str = "T",
    *,
    created: str = "2026-08-20T00:00:00.000Z",
    edited: str = "2026-08-22T00:00:00.000Z",
    object_: str = "page",
    url: str | None = None,
) -> dict[str, Any]:
    return {
        "id": pid,
        "object": object_,
        "url": url or f"https://notion.so/{pid}",
        "created_time": created,
        "last_edited_time": edited,
        "archived": False,
        "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}},
    }


def data_source(
    pid: str, title: str, *, edited: str = "2026-08-22T00:00:00.000Z"
) -> dict[str, Any]:
    return {
        "id": pid,
        "object": "data_source",
        "url": f"https://notion.so/{pid}",
        "created_time": "2026-01-01T00:00:00.000Z",
        "last_edited_time": edited,
        "title": [{"plain_text": title}],
    }


def para(bid: str, text: str, *, children: bool = False) -> dict[str, Any]:
    return {
        "id": bid,
        "type": "paragraph",
        "has_children": children,
        "paragraph": {"rich_text": [{"plain_text": text}]},
    }


def todo(bid: str, text: str, *, checked: bool) -> dict[str, Any]:
    return {
        "id": bid,
        "type": "to_do",
        "has_children": False,
        "to_do": {"rich_text": [{"plain_text": text}], "checked": checked},
    }


def child_page(bid: str, title: str) -> dict[str, Any]:
    return {"id": bid, "type": "child_page", "has_children": True, "child_page": {"title": title}}


def unsupported(bid: str) -> dict[str, Any]:
    return {"id": bid, "type": "unsupported", "has_children": False, "unsupported": {}}


def synced_mirror(bid: str) -> dict[str, Any]:
    return {
        "id": bid,
        "type": "synced_block",
        "has_children": True,
        "synced_block": {"synced_from": {"block_id": "orig"}},
    }


class FakeClient:
    def __init__(
        self,
        *,
        search: list[dict[str, Any]] | None = None,
        pages: dict[str, dict[str, Any]] | None = None,
        blocks: dict[str, list[dict[str, Any]]] | None = None,
        me: dict[str, Any] | None = None,
    ) -> None:
        self.search_results = search or []
        self.pages = pages or {}
        self.blocks = blocks or {}
        self.me = me or {"bot": {"workspace_name": "Test WS"}}
        self.closed = False

    async def users_me(self) -> dict[str, Any]:
        return self.me

    async def retrieve_page(self, pid: str) -> dict[str, Any]:
        if pid not in self.pages:
            raise NotionNotFound(f"not found: {pid}")
        return self.pages[pid]

    async def block_children(self, bid: str, *, max_items: int = 200) -> list[dict[str, Any]]:
        return list(self.blocks.get(bid, []))[:max_items]

    async def search(
        self, query: str | None = None, *, object_type: str | None = None, max_items: int = 100
    ) -> list[dict[str, Any]]:
        res = self.search_results
        if object_type:
            res = [r for r in res if r.get("object") == object_type]
        if query:
            res = [r for r in res if query.lower() in page_title(r).lower()]
        return res[:max_items]

    async def aclose(self) -> None:
        self.closed = True
