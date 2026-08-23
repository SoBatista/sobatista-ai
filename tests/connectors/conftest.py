from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sobai.auth import CredentialStore
from sobai.connectors.youtube import scopes
from sobai.connectors.youtube.oauth import TokenBundle, YouTubeAuth


@pytest.fixture
def yt_auth(mem_keyring):  # type: ignore[no-untyped-def]
    """A connected YouTubeAuth with a valid (non-expired) token in the mem keyring."""

    def _make(*, monetary: bool = False, captions: bool = False) -> YouTubeAuth:
        auth = YouTubeAuth(CredentialStore())
        auth.save_client("cid", "sec")
        auth.save_token(
            TokenBundle(
                access_token="valid-token",
                refresh_token="RT",
                expiry=datetime.now(UTC) + timedelta(hours=1),
                scope=" ".join(scopes.scope_set(monetary=monetary, captions=captions)),
            )
        )
        return auth

    return _make
