from __future__ import annotations

import httpx
import pytest

from sobai.providers.base import retry_async
from sobai.providers.http import is_retryable_http


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://x")
    return httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))


def test_retryable_classification() -> None:
    assert is_retryable_http(_status_error(500))
    assert is_retryable_http(_status_error(429))
    assert is_retryable_http(httpx.ConnectError("boom"))
    assert is_retryable_http(httpx.ReadTimeout("slow"))
    assert not is_retryable_http(_status_error(400))
    assert not is_retryable_http(_status_error(404))
    assert not is_retryable_http(ValueError("nope"))


async def test_retry_async_recovers() -> None:
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("boom")
        return "ok"

    result = await retry_async(
        flaky, is_retryable=is_retryable_http, retries=3, base_delay=0.0, max_delay=0.0
    )
    assert result == "ok"
    assert attempts["n"] == 3


async def test_retry_async_gives_up_on_fatal() -> None:
    async def fatal() -> str:
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        await retry_async(fatal, is_retryable=is_retryable_http, retries=3, base_delay=0.0)


async def test_retry_async_exhausts() -> None:
    async def always() -> str:
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        await retry_async(
            always, is_retryable=is_retryable_http, retries=2, base_delay=0.0, max_delay=0.0
        )
