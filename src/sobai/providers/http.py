"""Shared HTTPX plumbing for HTTP-based providers.

Centralizes client construction, retry classification, and error wrapping so the
concrete providers (Anthropic, OpenAI, Ollama) only implement wire-format
translation.
"""

from __future__ import annotations

from typing import Any

import httpx

from sobai.core.errors import ProviderError, ProviderUnavailableError
from sobai.core.redaction import redact
from sobai.core.retry import is_retryable_http

from .base import Provider

# Re-exported so provider adapters (and tests) can import it from here.
__all__ = ["HttpProvider", "is_retryable_http"]


class HttpProvider(Provider):
    """Base for providers that speak HTTP JSON."""

    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout_s: float = 120.0,
        retries: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_timeout = timeout_s
        self._retries = retries
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers or {},
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _wrap_status_error(self, exc: httpx.HTTPStatusError) -> ProviderError:
        """Turn an HTTP error into a redacted, actionable ProviderError."""
        status = exc.response.status_code
        try:
            body = exc.response.text
        except Exception:  # pragma: no cover
            body = ""
        snippet = redact(body)[:500]
        if status in (401, 403):
            return ProviderError(
                f"{self.name}: authentication failed (HTTP {status}).",
                hint="Check the stored credential with `sobai doctor` or re-run "
                f"`sobai init`. Server said: {snippet}",
            )
        if status == 404:
            return ProviderError(
                f"{self.name}: endpoint or model not found (HTTP 404). {snippet}",
                hint="Verify the model id with `sobai models discover`.",
            )
        if status == 429:
            return ProviderError(f"{self.name}: rate limited (HTTP 429). {snippet}")
        return ProviderError(f"{self.name}: request failed (HTTP {status}). {snippet}")

    def _wrap_transport_error(self, exc: httpx.TransportError) -> ProviderError:
        return ProviderUnavailableError(
            f"{self.name}: could not reach {self._base_url}: {redact(str(exc))}",
            hint="Check the service is running and reachable (see `sobai doctor`).",
        )

    async def _post(
        self, path: str, payload: dict[str, Any], *, timeout_s: float | None = None
    ) -> httpx.Response:
        try:
            resp = await self._client.post(
                path, json=payload, timeout=timeout_s or self._default_timeout
            )
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            raise self._wrap_status_error(exc) from exc
        except httpx.TransportError as exc:
            raise self._wrap_transport_error(exc) from exc

    async def _get(self, path: str, *, timeout_s: float | None = None) -> httpx.Response:
        try:
            resp = await self._client.get(path, timeout=timeout_s or self._default_timeout)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            raise self._wrap_status_error(exc) from exc
        except httpx.TransportError as exc:
            raise self._wrap_transport_error(exc) from exc
