from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from sobai.auth import CredentialStore
from sobai.connectors.youtube import oauth, scopes
from sobai.connectors.youtube.oauth import (
    TokenBundle,
    YouTubeAuth,
    build_auth_url,
    exchange_code,
    generate_pkce,
    generate_state,
    parse_redirect_query,
    refresh_access_token,
    validate_callback,
)
from sobai.core.errors import ConnectorError
from sobai.core.redaction import redact

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


# -- PKCE / state ----------------------------------------------------------
def test_pkce_challenge_is_s256_of_verifier() -> None:
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert challenge == expected
    assert "=" not in challenge


def test_state_is_unique() -> None:
    assert generate_state() != generate_state()


def test_build_auth_url_has_pkce_and_state() -> None:
    url = build_auth_url(
        client_id="cid",
        redirect_uri="http://127.0.0.1:1234",
        scopes=scopes.DEFAULT_SCOPES,
        code_challenge="chal",
        state="st8",
    )
    assert url.startswith(oauth.AUTH_ENDPOINT)
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url
    assert "state=st8" in url
    assert "access_type=offline" in url
    assert "redirect_uri=http" in url


def test_parse_redirect_query() -> None:
    q = parse_redirect_query("/?code=abc&state=xyz&scope=a%20b")
    assert q["code"] == "abc"
    assert q["state"] == "xyz"


# -- callback validation (state/CSRF) --------------------------------------
def test_validate_callback_success() -> None:
    assert validate_callback({"code": "c1", "state": "s1"}, "s1") == "c1"


def test_validate_callback_state_mismatch() -> None:
    with pytest.raises(ConnectorError, match="state mismatch"):
        validate_callback({"code": "c1", "state": "evil"}, "s1")


def test_validate_callback_error_param() -> None:
    with pytest.raises(ConnectorError, match="denied"):
        validate_callback({"error": "access_denied", "state": "s1"}, "s1")


def test_validate_callback_missing_code() -> None:
    with pytest.raises(ConnectorError):
        validate_callback({"state": "s1"}, "s1")


# -- token bundle ----------------------------------------------------------
def test_token_bundle_expiry_and_roundtrip() -> None:
    b = TokenBundle.from_response(
        {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "a b"},
        now=NOW,
    )
    assert not b.is_expired(NOW)
    assert b.is_expired(NOW + timedelta(seconds=3600))
    restored = TokenBundle.from_stored(b.to_stored())
    assert restored.access_token == "at"
    assert restored.refresh_token == "rt"
    assert restored.scopes() == ["a", "b"]


# -- token exchange / refresh (mocked) -------------------------------------
async def test_exchange_code_posts_pkce() -> None:
    with respx.mock(base_url="https://oauth2.googleapis.com") as mock:
        route = mock.post("/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "AT",
                    "refresh_token": "RT",
                    "expires_in": 3600,
                    "scope": "s",
                },
            )
        )
        async with httpx.AsyncClient() as http:
            bundle = await exchange_code(
                http,
                client_id="cid",
                client_secret="sec",
                code="CODE",
                code_verifier="VER",
                redirect_uri="http://127.0.0.1:1",
                now=NOW,
            )
    body = route.calls.last.request.content.decode()
    assert "code_verifier=VER" in body
    assert "grant_type=authorization_code" in body
    assert bundle.access_token == "AT"


async def test_refresh_keeps_prior_refresh_token() -> None:
    with respx.mock(base_url="https://oauth2.googleapis.com") as mock:
        mock.post("/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "AT2", "expires_in": 3600, "scope": "s"}
            )
        )
        async with httpx.AsyncClient() as http:
            bundle = await refresh_access_token(
                http, client_id="cid", client_secret="sec", refresh_token="RT", now=NOW
            )
    assert bundle.access_token == "AT2"
    assert bundle.refresh_token == "RT"  # response omitted it; prior kept


async def test_exchange_error_is_redacted() -> None:
    with respx.mock(base_url="https://oauth2.googleapis.com") as mock:
        mock.post("/token").mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        async with httpx.AsyncClient() as http:
            with pytest.raises(ConnectorError):
                await exchange_code(
                    http,
                    client_id="cid",
                    client_secret="sec",
                    code="C",
                    code_verifier="V",
                    redirect_uri="http://127.0.0.1:1",
                )


# -- YouTubeAuth (keyring + refresh) ---------------------------------------
async def test_auth_refreshes_expired_token(mem_keyring) -> None:
    creds = CredentialStore()
    auth = YouTubeAuth(creds)
    auth.save_client("cid", "sec")
    expired = TokenBundle(
        access_token="old",
        refresh_token="RT",
        expiry=NOW - timedelta(hours=1),
        scope="s",
    )
    auth.save_token(expired)
    with respx.mock(base_url="https://oauth2.googleapis.com") as mock:
        mock.post("/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "fresh", "expires_in": 3600, "scope": "s"}
            )
        )
        async with httpx.AsyncClient() as http:
            token = await auth.access_token(http, now=NOW)
    assert token == "fresh"
    # persisted
    assert auth.load_token().access_token == "fresh"


async def test_auth_returns_valid_token_without_refresh(mem_keyring) -> None:
    creds = CredentialStore()
    auth = YouTubeAuth(creds)
    auth.save_client("cid", "sec")
    auth.save_token(
        TokenBundle(
            access_token="valid", refresh_token="RT", expiry=NOW + timedelta(hours=1), scope="s"
        )
    )
    async with httpx.AsyncClient() as http:
        assert await auth.access_token(http, now=NOW) == "valid"


def test_saved_token_is_registered_for_redaction(mem_keyring) -> None:
    creds = CredentialStore()
    auth = YouTubeAuth(creds)
    auth.save_token(
        TokenBundle(
            access_token="supersecrettoken123",
            refresh_token="refreshsecret456",
            expiry=NOW,
            scope="s",
        )
    )
    assert "supersecrettoken123" not in redact("leak supersecrettoken123")
    assert "refreshsecret456" not in redact("leak refreshsecret456")
