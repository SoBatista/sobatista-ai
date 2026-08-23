from __future__ import annotations

import re

import httpx
import pytest
import respx

from sobai.connectors.notion.client import (
    NOTION_VERSION,
    NotionApiError,
    NotionAuthError,
    NotionClient,
    NotionNotFound,
    NotionPermissionError,
)

SEARCH = "https://api.notion.com/v1/search"
ME = "https://api.notion.com/v1/users/me"
CHILDREN = re.compile(r"https://api\.notion\.com/v1/blocks/B1/children.*")


def _err(status: int, code: str, message: str = "nope") -> httpx.Response:
    return httpx.Response(
        status, json={"object": "error", "status": status, "code": code, "message": message}
    )


async def test_search_pagination_and_headers() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(
            side_effect=[
                httpx.Response(
                    200, json={"results": [{"id": "1"}], "has_more": True, "next_cursor": "c2"}
                ),
                httpx.Response(
                    200, json={"results": [{"id": "2"}], "has_more": False, "next_cursor": None}
                ),
            ]
        )
        client = NotionClient("secret-token-xyz")
        items = await client.search("q", max_items=100)
        await client.aclose()
    assert [i["id"] for i in items] == ["1", "2"]
    req = route.calls[0].request
    assert req.headers["Notion-Version"] == NOTION_VERSION
    assert req.headers["authorization"] == "Bearer secret-token-xyz"


async def test_block_children_pagination() -> None:
    with respx.mock as mock:
        mock.get(CHILDREN).mock(
            side_effect=[
                httpx.Response(
                    200, json={"results": [{"id": "a"}], "has_more": True, "next_cursor": "c2"}
                ),
                httpx.Response(200, json={"results": [{"id": "b"}], "has_more": False}),
            ]
        )
        client = NotionClient("t")
        items = await client.block_children("B1", max_items=100)
        await client.aclose()
    assert [i["id"] for i in items] == ["a", "b"]


async def test_users_me() -> None:
    with respx.mock as mock:
        mock.get(ME).mock(return_value=httpx.Response(200, json={"bot": {"workspace_name": "W"}}))
        client = NotionClient("t")
        me = await client.users_me()
        await client.aclose()
    assert me["bot"]["workspace_name"] == "W"


async def test_error_mapping() -> None:
    cases = [
        (401, "unauthorized", NotionAuthError),
        (403, "restricted_resource", NotionPermissionError),
        (404, "object_not_found", NotionNotFound),
    ]
    for status, code, exc_type in cases:
        with respx.mock as mock:
            mock.get(ME).mock(return_value=_err(status, code))
            client = NotionClient("t", retries=0)
            with pytest.raises(exc_type):
                await client.users_me()
            await client.aclose()


async def test_rate_limit_retry_after_then_success() -> None:
    with respx.mock as mock:
        mock.get(ME).mock(
            side_effect=[
                httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    json={"object": "error", "code": "rate_limited"},
                ),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        client = NotionClient("t")
        me = await client.users_me()
        await client.aclose()
    assert me["ok"] is True


async def test_server_error_retried() -> None:
    with respx.mock as mock:
        mock.get(ME).mock(
            side_effect=[_err(500, "internal_server_error"), httpx.Response(200, json={"ok": 1})]
        )
        client = NotionClient("t")
        assert (await client.users_me())["ok"] == 1
        await client.aclose()


async def test_error_body_token_redacted() -> None:
    with respx.mock as mock:
        mock.get(ME).mock(
            return_value=_err(400, "validation_error", "leaked secret-token-xyz in message")
        )
        client = NotionClient("secret-token-xyz", retries=0)
        with pytest.raises(NotionApiError) as exc:
            await client.users_me()
        await client.aclose()
    assert "secret-token-xyz" not in str(exc.value)


async def test_transport_error_wrapped() -> None:
    with respx.mock as mock:
        mock.get(ME).mock(side_effect=httpx.ConnectError("boom"))
        client = NotionClient("t", retries=0)
        with pytest.raises(NotionApiError):
            await client.users_me()
        await client.aclose()
