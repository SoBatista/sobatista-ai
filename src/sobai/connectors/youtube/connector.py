"""The YouTube connector: assembles auth, client, and the read-only tool set."""

from __future__ import annotations

from sobai.auth import CredentialStore
from sobai.connectors.base import Connector, ConnectorStatus
from sobai.core.classification import DataClass
from sobai.tools import ToolRegistry

from . import scopes as scope_defs
from .client import YouTubeClient
from .oauth import YouTubeAuth
from .tools import build_registry


class YouTubeConnector(Connector):
    name = "youtube"
    default_data_class = DataClass.INTERNAL

    def __init__(self, creds: CredentialStore, *, timeout_s: float = 30.0) -> None:
        self._auth = YouTubeAuth(creds)
        self._timeout = timeout_s
        self._client: YouTubeClient | None = None

    @property
    def auth(self) -> YouTubeAuth:
        return self._auth

    def is_connected(self) -> bool:
        return self._auth.is_connected()

    def monetary_granted(self) -> bool:
        return scope_defs.ANALYTICS_MONETARY in self._auth.granted_scopes()

    def captions_granted(self) -> bool:
        return scope_defs.CAPTIONS_FORCE_SSL in self._auth.granted_scopes()

    def client(self) -> YouTubeClient:
        if self._client is None:
            self._client = YouTubeClient(self._auth, timeout_s=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def tools(self) -> ToolRegistry:
        return build_registry(self.client(), monetary_granted=self.monetary_granted())

    def status(self) -> ConnectorStatus:
        granted = tuple(self._auth.granted_scopes())
        if self.is_connected():
            detail = "connected"
        elif self._auth.has_client():
            detail = "OAuth client configured, not yet authorized"
        else:
            detail = "not connected"
        return ConnectorStatus(
            name=self.name,
            connected=self.is_connected(),
            detail=detail,
            scopes=granted,
        )
