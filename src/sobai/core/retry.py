"""Provider- and connector-neutral HTTP retry helpers.

Lives in ``core`` so both providers and connectors can use it without importing
each other (the two abstractions must stay decoupled).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx


def is_retryable_http(exc: Exception) -> bool:
    """Classify an exception raised during an HTTP call as retryable or fatal."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status in (408, 409, 425, 429) or status >= 500
    return False


async def retry_async[T](
    factory: Callable[[], Awaitable[T]],
    *,
    is_retryable: Callable[[Exception], bool],
    retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> T:
    """Run ``factory`` with bounded exponential backoff on retryable errors.

    ``retries`` is the number of *additional* attempts after the first (total
    attempts == ``retries + 1``). Non-retryable exceptions propagate immediately.
    """
    attempt = 0
    while True:
        try:
            return await factory()
        except Exception as exc:
            if attempt >= retries or not is_retryable(exc):
                raise
            delay = min(max_delay, base_delay * (2**attempt))
            delay = random.uniform(0, delay)  # noqa: S311 - jitter, not security
            await asyncio.sleep(delay)
            attempt += 1
