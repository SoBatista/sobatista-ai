"""Installed-application OAuth 2.0 for the YouTube connector.

Implements the Google-recommended native-app flow: a loopback redirect
(``http://127.0.0.1:<port>``) with PKCE (S256) and ``state`` validation. Tokens
are stored only in the OS keyring and are registered for redaction on load.

The network- and browser-independent pieces (PKCE, auth-URL building, redirect
parsing, token exchange/refresh) are separated from the interactive loopback flow
so they can be unit-tested without a browser or live credentials.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import secrets
import time
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from sobai.auth import CredentialStore
from sobai.core.errors import ConnectorError
from sobai.core.redaction import redact, register_secret

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

CLIENT_KEY = "connector:youtube:oauth_client"  # {client_id, client_secret}
TOKEN_KEY = "connector:youtube:token"  # token bundle

_EXPIRY_SKEW_S = 60


# --------------------------------------------------------------------------- #
# PKCE / state / URL (pure)
# --------------------------------------------------------------------------- #
def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` using S256.

    Verifier is 43-128 chars of the unreserved set (token_urlsafe gives that);
    challenge is the base64url(sha256(verifier)) with padding stripped.
    """
    verifier = secrets.token_urlsafe(64)  # ~86 chars, within [43,128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_auth_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    code_challenge: str,
    state: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        # Guarantee a refresh token for installed apps.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def parse_redirect_query(path: str) -> dict[str, str]:
    """Extract query params from a redirect request path (e.g. ``/?code=..&state=..``)."""
    query = urllib.parse.urlparse(path).query
    flat = urllib.parse.parse_qs(query)
    return {k: v[0] for k, v in flat.items() if v}


def validate_callback(captured: dict[str, str], expected_state: str) -> str:
    """Validate an OAuth redirect and return the authorization code.

    Enforces the CSRF ``state`` match and surfaces provider errors. Pure, so the
    state/error handling is unit-testable without a browser.
    """
    if not captured:
        raise ConnectorError("Timed out waiting for OAuth authorization.")
    if captured.get("error"):
        raise ConnectorError(f"Authorization denied: {captured['error']}")
    if captured.get("state") != expected_state:
        raise ConnectorError("OAuth state mismatch - possible CSRF; aborting.")
    code = captured.get("code")
    if not code:
        raise ConnectorError("No authorization code returned.")
    return code


# --------------------------------------------------------------------------- #
# Token bundle
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class TokenBundle:
    access_token: str
    refresh_token: str | None
    expiry: datetime
    scope: str
    token_type: str = "Bearer"

    @classmethod
    def from_response(
        cls, data: dict[str, Any], *, now: datetime, prior_refresh: str | None = None
    ) -> TokenBundle:
        expires_in = int(data.get("expires_in", 3600))
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token") or prior_refresh,
            expiry=now + timedelta(seconds=expires_in),
            scope=data.get("scope", ""),
            token_type=data.get("token_type", "Bearer"),
        )

    @classmethod
    def from_stored(cls, data: dict[str, Any]) -> TokenBundle:
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expiry=datetime.fromisoformat(data["expiry"]),
            scope=data.get("scope", ""),
            token_type=data.get("token_type", "Bearer"),
        )

    def to_stored(self) -> dict[str, str]:
        out = {
            "access_token": self.access_token,
            "expiry": self.expiry.isoformat(),
            "scope": self.scope,
            "token_type": self.token_type,
        }
        if self.refresh_token:
            out["refresh_token"] = self.refresh_token
        return out

    def is_expired(self, now: datetime) -> bool:
        return now + timedelta(seconds=_EXPIRY_SKEW_S) >= self.expiry

    def scopes(self) -> list[str]:
        return self.scope.split()


def _raise_token_error(resp: httpx.Response) -> None:
    detail = redact(resp.text)[:400]
    raise ConnectorError(
        f"YouTube OAuth token request failed (HTTP {resp.status_code}): {detail}",
        hint="Re-run `sobai connect youtube`. Check the Desktop OAuth client id/secret.",
    )


async def exchange_code(
    http: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    now: datetime | None = None,
    token_url: str = TOKEN_ENDPOINT,
) -> TokenBundle:
    """Exchange an authorization code for tokens (PKCE)."""
    data = {
        "client_id": client_id,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client_secret:
        data["client_secret"] = client_secret
    resp = await http.post(token_url, data=data)
    if resp.status_code >= 400:
        _raise_token_error(resp)
    return TokenBundle.from_response(resp.json(), now=now or datetime.now(UTC))


async def refresh_access_token(
    http: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    now: datetime | None = None,
    token_url: str = TOKEN_ENDPOINT,
) -> TokenBundle:
    """Exchange a refresh token for a fresh access token."""
    data = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        data["client_secret"] = client_secret
    resp = await http.post(token_url, data=data)
    if resp.status_code >= 400:
        _raise_token_error(resp)
    # A refresh response usually omits refresh_token; keep the existing one.
    return TokenBundle.from_response(
        resp.json(), now=now or datetime.now(UTC), prior_refresh=refresh_token
    )


# --------------------------------------------------------------------------- #
# Interactive loopback authorization
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AuthorizationResult:
    code: str
    code_verifier: str
    redirect_uri: str


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured: dict[str, str] = {}  # noqa: RUF012 - class-level capture slot

    def do_GET(self) -> None:
        type(self).captured = parse_redirect_query(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            b"<html><body><h2>SoBatista AI</h2>"
            b"<p>Authorization received. You can close this tab and return to the "
            b"terminal.</p></body></html>"
        )
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence default logging
        return


def run_loopback_authorization(
    *,
    client_id: str,
    scopes: list[str],
    open_browser: bool = True,
    timeout_s: float = 300.0,
    emit: Callable[[str], None] | None = None,
) -> AuthorizationResult:  # pragma: no cover - requires a browser + network
    """Run the interactive loopback + PKCE authorization and return the code.

    This is the only browser/network-dependent part of the flow; its constituent
    helpers (PKCE, URL building, redirect parsing) are unit-tested separately.
    """
    verifier, challenge = generate_pkce()
    state = generate_state()
    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.timeout = 1.0
    _CallbackHandler.captured = {}
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}"
    url = build_auth_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        code_challenge=challenge,
        state=state,
    )
    if emit:
        emit(f"Open this URL to authorize (also attempting to open your browser):\n{url}")
    if open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    deadline = time.monotonic() + timeout_s
    while not _CallbackHandler.captured and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()

    code = validate_callback(_CallbackHandler.captured, state)
    return AuthorizationResult(code=code, code_verifier=verifier, redirect_uri=redirect_uri)


# --------------------------------------------------------------------------- #
# Token store / refresh manager
# --------------------------------------------------------------------------- #
class YouTubeAuth:
    """Loads, refreshes, and persists YouTube OAuth credentials via the keyring."""

    def __init__(self, creds: CredentialStore) -> None:
        self._creds = creds

    # -- OAuth client (id/secret) -----------------------------------------
    def has_client(self) -> bool:
        return self._creds.get_json(CLIENT_KEY) is not None

    def save_client(self, client_id: str, client_secret: str | None) -> None:
        bundle = {"client_id": client_id}
        if client_secret:
            bundle["client_secret"] = client_secret
        self._creds.set_json(CLIENT_KEY, bundle)

    def _client(self) -> tuple[str, str | None]:
        data = self._creds.get_json(CLIENT_KEY)
        if not data:
            raise ConnectorError(
                "No YouTube OAuth client configured.",
                hint="Run `sobai connect youtube` and provide your Desktop OAuth client.",
            )
        return data["client_id"], data.get("client_secret")

    # -- tokens ------------------------------------------------------------
    def has_token(self) -> bool:
        return self._creds.get_json(TOKEN_KEY) is not None

    def is_connected(self) -> bool:
        return self.has_client() and self.has_token()

    def load_token(self) -> TokenBundle | None:
        data = self._creds.get_json(TOKEN_KEY)
        return TokenBundle.from_stored(data) if data else None

    def save_token(self, bundle: TokenBundle) -> None:
        register_secret(bundle.access_token)
        if bundle.refresh_token:
            register_secret(bundle.refresh_token)
        self._creds.set_json(TOKEN_KEY, bundle.to_stored())

    def granted_scopes(self) -> list[str]:
        bundle = self.load_token()
        return bundle.scopes() if bundle else []

    def clear(self) -> None:
        self._creds.delete(TOKEN_KEY)
        self._creds.delete(CLIENT_KEY)

    async def access_token(
        self, http: httpx.AsyncClient, *, now: datetime | None = None, force: bool = False
    ) -> str:
        """Return a valid access token, refreshing (and persisting) if expired.

        ``force=True`` refreshes unconditionally — used to recover from a 401 on a
        token the server considers invalid before its computed expiry.
        """
        now = now or datetime.now(UTC)
        bundle = self.load_token()
        if bundle is None:
            raise ConnectorError("YouTube is not connected.", hint="Run `sobai connect youtube`.")
        if not force and not bundle.is_expired(now):
            return bundle.access_token
        if not bundle.refresh_token:
            raise ConnectorError(
                "Access token expired and no refresh token is available.",
                hint="Re-run `sobai connect youtube`.",
            )
        client_id, client_secret = self._client()
        refreshed = await refresh_access_token(
            http,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=bundle.refresh_token,
            now=now,
        )
        self.save_token(refreshed)
        return refreshed.access_token
