"""Async HTTP client for the YouTube Data API v3 and Analytics API v2.

Handles bearer auth with automatic token refresh (including a one-shot refresh on
a 401), bounded classified retries, id-chunked video lookups, and redacted error
wrapping. Uses only official Google endpoints — never scrapes.
"""

from __future__ import annotations

from typing import Any

import httpx

from sobai.core.errors import ConnectorError
from sobai.core.redaction import redact
from sobai.core.retry import is_retryable_http, retry_async

from .oauth import YouTubeAuth

DATA_BASE = "https://www.googleapis.com/youtube/v3"
ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2"

_VIDEOS_LIST_CHUNK = 50  # Data API max ids per videos.list call


class YouTubeApiError(ConnectorError):
    """A YouTube API request failed."""


class UnsupportedQueryError(YouTubeApiError):
    """The requested metric/dimension/filter combination is not supported."""


def _parse_google_error(resp: httpx.Response) -> tuple[str, str | None]:
    """Return (message, reason) from a Google API error body, redacted."""
    try:
        err = resp.json().get("error", {})
        message = err.get("message", resp.text)
        reason = None
        errors = err.get("errors")
        if isinstance(errors, list) and errors:
            reason = errors[0].get("reason")
        return redact(str(message))[:400], reason
    except Exception:
        return redact(resp.text)[:400], None


class YouTubeClient:
    def __init__(self, auth: YouTubeAuth, *, timeout_s: float = 30.0, retries: int = 2) -> None:
        self._auth = auth
        self._http = httpx.AsyncClient(timeout=timeout_s)
        self._retries = retries

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- core request ------------------------------------------------------
    async def _request(self, url: str, params: dict[str, Any]) -> httpx.Response:
        async def _once(force_refresh: bool) -> httpx.Response:
            token = await self._auth.access_token(self._http, force=force_refresh)
            return await self._http.get(
                url, params=params, headers={"Authorization": f"Bearer {token}"}
            )

        async def _attempt() -> httpx.Response:
            resp = await _once(force_refresh=False)
            if resp.status_code == 401:
                # Token rejected before its computed expiry — refresh once and retry.
                resp = await _once(force_refresh=True)
            resp.raise_for_status()
            return resp

        try:
            return await retry_async(
                _attempt, is_retryable=is_retryable_http, retries=self._retries
            )
        except httpx.HTTPStatusError as exc:
            self._raise_for_status(exc)
        except httpx.TransportError as exc:
            raise YouTubeApiError(
                f"Could not reach YouTube API: {redact(str(exc))}",
                hint="Check your network connection and try again.",
            ) from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def _raise_for_status(self, exc: httpx.HTTPStatusError) -> None:
        status = exc.response.status_code
        message, reason = _parse_google_error(exc.response)
        if status == 400 and reason in ("badRequest", "invalidParameter", None):
            raise UnsupportedQueryError(
                f"YouTube Analytics rejected this query (HTTP 400): {message}",
                hint="This metric/dimension/filter combination is not supported.",
            ) from exc
        if status in (401, 403):
            raise YouTubeApiError(
                f"Not authorized (HTTP {status}): {message}",
                hint="You may lack the required scope. Re-run `sobai connect youtube` "
                "(add --monetary or --captions if needed).",
            ) from exc
        if status == 429:
            raise YouTubeApiError(f"Rate limited by YouTube API (HTTP 429): {message}") from exc
        raise YouTubeApiError(f"YouTube API error (HTTP {status}): {message}") from exc

    async def _get_json(self, base: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request(f"{base}/{path}", params)
        data: dict[str, Any] = resp.json()
        return data

    # -- Data API ----------------------------------------------------------
    async def get_channel(self) -> dict[str, Any]:
        data = await self._get_json(
            DATA_BASE,
            "channels",
            {"part": "snippet,statistics,contentDetails", "mine": "true"},
        )
        items: list[dict[str, Any]] = data.get("items", [])
        if not items:
            raise YouTubeApiError(
                "No channel found for the authorized account.",
                hint="Ensure the Google account you authorized owns a YouTube channel.",
            )
        return items[0]

    async def list_videos(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fetch video resources, chunking ids to the API's 50-per-call limit."""
        out: list[dict[str, Any]] = []
        for i in range(0, len(ids), _VIDEOS_LIST_CHUNK):
            chunk = ids[i : i + _VIDEOS_LIST_CHUNK]
            data = await self._get_json(
                DATA_BASE,
                "videos",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk)},
            )
            out.extend(data.get("items", []))
        return out

    async def list_captions(self, video_id: str) -> list[dict[str, Any]]:
        data = await self._get_json(DATA_BASE, "captions", {"part": "snippet", "videoId": video_id})
        items: list[dict[str, Any]] = data.get("items", [])
        return items

    async def download_caption(self, caption_id: str, *, fmt: str = "srt") -> str:
        resp = await self._request(f"{DATA_BASE}/captions/{caption_id}", {"tfmt": fmt})
        return resp.text

    # -- Analytics API -----------------------------------------------------
    async def query_analytics(
        self,
        *,
        start: str,
        end: str,
        metrics: list[str],
        dimensions: list[str] | None = None,
        filters: str | None = None,
        sort: str | None = None,
        max_results: int | None = None,
        start_index: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start,
            "endDate": end,
            "metrics": ",".join(metrics),
        }
        if dimensions:
            params["dimensions"] = ",".join(dimensions)
        if filters:
            params["filters"] = filters
        if sort:
            params["sort"] = sort
        if max_results is not None:
            params["maxResults"] = max_results
        if start_index is not None:
            params["startIndex"] = start_index
        return await self._get_json(ANALYTICS_BASE, "reports", params)
