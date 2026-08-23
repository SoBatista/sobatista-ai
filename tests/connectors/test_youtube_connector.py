from __future__ import annotations

import asyncio

from sobai.auth import CredentialStore
from sobai.connectors.youtube import YouTubeConnector


def test_connected_status_and_flags(yt_auth) -> None:
    yt_auth(monetary=True, captions=True)  # seeds token into the shared mem keyring
    conn = YouTubeConnector(CredentialStore())
    assert conn.is_connected()
    assert conn.monetary_granted()
    assert conn.captions_granted()
    status = conn.status()
    assert status.connected
    assert status.detail == "connected"
    assert status.name == "youtube"
    registry = conn.tools()
    assert len(registry) >= 7
    asyncio.run(conn.aclose())


def test_not_connected_status(mem_keyring) -> None:
    conn = YouTubeConnector(CredentialStore())
    assert not conn.is_connected()
    assert not conn.monetary_granted()
    status = conn.status()
    assert not status.connected
    assert status.detail == "not connected"


def test_client_configured_not_authorized(mem_keyring) -> None:
    creds = CredentialStore()
    conn = YouTubeConnector(creds)
    conn.auth.save_client("cid", "sec")
    assert not conn.is_connected()
    assert "not yet authorized" in conn.status().detail
