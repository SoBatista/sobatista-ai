"""Async HTTP client for the official Notion API (read-only use).

Handles bearer auth + the required ``Notion-Version`` header, cursor pagination,
rate-limit handling (HTTP 429 with ``Retry-After`` seconds, and 529 overload)
with bounded retries, timeouts, and redacted error mapping. Only GET/POST
*read* endpoints are used; nothing mutates Notion content.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx

from sobai.core.errors import AuthError, ConnectorError, NotFoundError, PolicyError
from sobai.core.redaction import redact, register_secret

BASE_URL = "https://api.notion.com/v1"
# Current documented Notion API version (see docs/notion.md). Object shapes are
# feature-detected (page / data_source / legacy database) rather than assumed.
NOTION_VERSION = "2026-03-11"

_PAGE_SIZE = 100  # API maximum
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP = 30.0


class NotionApiError(ConnectorError):
    """A Notion API request failed."""


class NotionAuthError(AuthError):
    """The Notion token is missing, invalid, or revoked."""


class NotionPermissionError(PolicyError):
    """The integration lacks access to the requested content (not shared)."""


class NotionNotFound(NotFoundError):
    """The page/block was not found, is not shared, or was deleted."""


def _error_detail(resp: httpx.Response) -> tuple[str, str]:
    try:
        body = resp.json()
        return str(body.get("code", "")), redact(str(body.get("message", "")))[:400]
    except Exception:
        return "", redact(resp.text)[:400]


class NotionClient:
    def __init__(self, token: str, *, timeout_s: float = 30.0, retries: int = _MAX_RETRIES) -> None:
        register_secret(token)  # scrub the token from any output/logs/errors
        self._retries = retries
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout_s,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- core request with rate-limit-aware retries ------------------------
    async def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                resp = await self._http.request(method, path, json=json_body)
            except httpx.TransportError as exc:
                if attempt < self._retries:
                    await self._sleep_backoff(attempt)
                    attempt += 1
                    continue
                raise NotionApiError(
                    f"Could not reach the Notion API: {redact(str(exc))}",
                    hint="Check your network connection and try again.",
                ) from exc

            if resp.status_code < 400:
                data: dict[str, Any] = resp.json()
                return data

            # Rate limited / overloaded → honor Retry-After, then retry.
            if resp.status_code in (429, 529) and attempt < self._retries:
                await self._sleep_retry_after(resp, attempt)
                attempt += 1
                continue
            if resp.status_code >= 500 and attempt < self._retries:
                await self._sleep_backoff(attempt)
                attempt += 1
                continue
            self._raise(resp)

    async def _sleep_retry_after(self, resp: httpx.Response, attempt: int) -> None:
        header = resp.headers.get("Retry-After")
        try:
            delay = float(header) if header is not None else None
        except ValueError:
            delay = None
        if delay is None:
            await self._sleep_backoff(attempt)
            return
        await asyncio.sleep(min(delay, _MAX_RETRY_SLEEP))

    async def _sleep_backoff(self, attempt: int) -> None:
        base = min(_MAX_RETRY_SLEEP, 0.5 * (2**attempt))
        await asyncio.sleep(random.uniform(0, base))  # noqa: S311 - jitter, not security

    def _raise(self, resp: httpx.Response) -> None:
        code, message = _error_detail(resp)
        status = resp.status_code
        if status == 401:
            raise NotionAuthError(
                f"Notion authentication failed (401 {code}): {message}",
                hint="Re-run `sobai connect notion` with a valid integration token.",
            )
        if status == 403 or code == "restricted_resource":
            raise NotionPermissionError(
                f"Notion access denied (403 {code}): {message}",
                hint="Share the page/database with your integration in Notion.",
            )
        if status == 404 or code == "object_not_found":
            raise NotionNotFound(
                f"Notion object not found or not shared (404 {code}): {message}",
                hint="Confirm the id and that the page is shared with your integration.",
            )
        if status == 429:
            raise NotionApiError(f"Notion rate limit exceeded (429): {message}")
        raise NotionApiError(f"Notion API error (HTTP {status} {code}): {message}")

    # -- endpoints ---------------------------------------------------------
    async def users_me(self) -> dict[str, Any]:
        """Return the bot user for this token (validates the token)."""
        return await self._request("GET", "/users/me")

    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/pages/{page_id}")

    async def _paginate(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        max_items: int = 1000,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body = dict(json_body or {})
            params = ""
            if method == "GET":
                params = f"?page_size={_PAGE_SIZE}" + (f"&start_cursor={cursor}" if cursor else "")
                data = await self._request("GET", path + params)
            else:
                body["page_size"] = _PAGE_SIZE
                if cursor:
                    body["start_cursor"] = cursor
                data = await self._request(method, path, json_body=body)
            items.extend(data.get("results", []))
            if len(items) >= max_items or not data.get("has_more"):
                return items[:max_items]
            cursor = data.get("next_cursor")
            if not cursor:
                return items[:max_items]

    async def search(
        self,
        query: str | None = None,
        *,
        object_type: str | None = None,
        max_items: int = 100,
    ) -> list[dict[str, Any]]:
        """Search pages/data_sources shared with the integration (by title)."""
        body: dict[str, Any] = {
            "sort": {"direction": "descending", "timestamp": "last_edited_time"}
        }
        if query:
            body["query"] = query
        if object_type:
            body["filter"] = {"property": "object", "value": object_type}
        return await self._paginate("POST", "/search", json_body=body, max_items=max_items)

    async def block_children(self, block_id: str, *, max_items: int = 200) -> list[dict[str, Any]]:
        return await self._paginate("GET", f"/blocks/{block_id}/children", max_items=max_items)

    async def iter_search(
        self, query: str | None = None, *, object_type: str | None = None, max_items: int = 100
    ) -> AsyncIterator[dict[str, Any]]:  # pragma: no cover - convenience
        for item in await self.search(query, object_type=object_type, max_items=max_items):
            yield item
