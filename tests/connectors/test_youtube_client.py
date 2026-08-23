from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from sobai.auth import CredentialStore
from sobai.connectors.youtube.client import (
    ANALYTICS_BASE,
    DATA_BASE,
    UnsupportedQueryError,
    YouTubeApiError,
    YouTubeClient,
)
from sobai.connectors.youtube.oauth import TokenBundle, YouTubeAuth

CHANNELS_URL = f"{DATA_BASE}/channels"
VIDEOS_URL = f"{DATA_BASE}/videos"
REPORTS_URL = f"{ANALYTICS_BASE}/reports"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _auth(*, access_token: str = "valid-token") -> YouTubeAuth:
    auth = YouTubeAuth(CredentialStore())
    auth.save_client("cid", "sec")
    auth.save_token(
        TokenBundle(
            access_token=access_token,
            refresh_token="RT",
            expiry=datetime.now(UTC) + timedelta(hours=1),
            scope="https://www.googleapis.com/auth/youtube.readonly",
        )
    )
    return auth


async def test_get_channel(mem_keyring) -> None:
    client = YouTubeClient(_auth())
    with respx.mock as mock:
        mock.get(CHANNELS_URL).mock(
            return_value=httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {}}]})
        )
        ch = await client.get_channel()
    await client.aclose()
    assert ch["id"] == "UC1"


async def test_list_videos_chunks_over_50(mem_keyring) -> None:
    client = YouTubeClient(_auth())
    ids = [f"vid{i:02d}____" for i in range(60)]  # 60 ids -> 2 calls
    with respx.mock as mock:
        route = mock.get(VIDEOS_URL).mock(
            return_value=httpx.Response(200, json={"items": [{"id": "x"}]})
        )
        await client.list_videos(ids)
    await client.aclose()
    assert route.call_count == 2  # chunked at 50


async def test_query_analytics_builds_params(mem_keyring) -> None:
    client = YouTubeClient(_auth())
    with respx.mock as mock:
        route = mock.get(REPORTS_URL).mock(
            return_value=httpx.Response(200, json={"columnHeaders": [], "rows": []})
        )
        await client.query_analytics(
            start="2026-01-01",
            end="2026-01-31",
            metrics=["views"],
            dimensions=["day"],
            sort="-views",
            max_results=10,
        )
    await client.aclose()
    req = route.calls.last.request
    assert req.url.params["ids"] == "channel==MINE"
    assert req.url.params["metrics"] == "views"
    assert req.url.params["dimensions"] == "day"
    assert req.url.params["maxResults"] == "10"


async def test_analytics_400_is_unsupported_query(mem_keyring) -> None:
    client = YouTubeClient(_auth())
    with respx.mock as mock:
        mock.get(REPORTS_URL).mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "bad combo",
                        "errors": [{"reason": "badRequest"}],
                    }
                },
            )
        )
        with pytest.raises(UnsupportedQueryError):
            await client.query_analytics(start="2026-01-01", end="2026-01-31", metrics=["x"])
    await client.aclose()


async def test_403_is_authorization_error(mem_keyring) -> None:
    client = YouTubeClient(_auth())
    with respx.mock as mock:
        mock.get(CHANNELS_URL).mock(
            return_value=httpx.Response(
                403,
                json={
                    "error": {
                        "code": 403,
                        "message": "insufficient",
                        "errors": [{"reason": "forbidden"}],
                    }
                },
            )
        )
        with pytest.raises(YouTubeApiError):
            await client.get_channel()
    await client.aclose()


async def test_rate_limit_then_success(mem_keyring) -> None:
    client = YouTubeClient(_auth(), retries=2)
    with respx.mock as mock:
        mock.get(CHANNELS_URL).mock(
            side_effect=[
                httpx.Response(429, json={"error": {"message": "slow down"}}),
                httpx.Response(200, json={"items": [{"id": "UC1"}]}),
            ]
        )
        ch = await client.get_channel()
    await client.aclose()
    assert ch["id"] == "UC1"


async def test_401_triggers_refresh_and_retry(mem_keyring) -> None:
    client = YouTubeClient(_auth(access_token="stale"))
    with respx.mock as mock:
        mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "refreshed", "expires_in": 3600, "scope": "s"}
            )
        )
        mock.get(CHANNELS_URL).mock(
            side_effect=[
                httpx.Response(401, json={"error": {"message": "expired"}}),
                httpx.Response(200, json={"items": [{"id": "UC1"}]}),
            ]
        )
        ch = await client.get_channel()
    await client.aclose()
    assert ch["id"] == "UC1"


async def test_error_body_token_is_redacted(mem_keyring) -> None:
    client = YouTubeClient(_auth(access_token="SUPERSECRETTOKEN999"), retries=0)
    with respx.mock as mock:
        # Simulate an upstream error body that echoes the token.
        mock.get(CHANNELS_URL).mock(
            return_value=httpx.Response(
                500, json={"error": {"message": "boom SUPERSECRETTOKEN999"}}
            )
        )
        with pytest.raises(YouTubeApiError) as exc:
            await client.get_channel()
    await client.aclose()
    assert "SUPERSECRETTOKEN999" not in str(exc.value)
