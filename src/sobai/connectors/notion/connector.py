"""The Notion connector: assembles auth, client, and the read-only tool set."""

from __future__ import annotations

from sobai.auth import CredentialStore
from sobai.connectors.base import Connector, ConnectorStatus
from sobai.core.classification import DataClass
from sobai.tools import ToolRegistry

from .auth import NotionAuth
from .client import NotionClient
from .tools import build_registry


class NotionConnector(Connector):
    name = "notion"
    default_data_class = DataClass.INTERNAL

    def __init__(self, creds: CredentialStore, *, timeout_s: float = 30.0) -> None:
        self._auth = NotionAuth(creds)
        self._timeout = timeout_s
        self._client: NotionClient | None = None

    @property
    def auth(self) -> NotionAuth:
        return self._auth

    def is_connected(self) -> bool:
        return self._auth.has_token()

    def client(self) -> NotionClient:
        if self._client is None:
            self._client = NotionClient(self._auth.token(), timeout_s=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def tools(self) -> ToolRegistry:
        return build_registry(self.client())

    def status(self) -> ConnectorStatus:
        connected = self.is_connected()
        return ConnectorStatus(
            name=self.name,
            connected=connected,
            detail="connected" if connected else "not connected",
        )
