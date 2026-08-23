"""Notion integration-token storage — keyring only.

The token is accepted through a hidden prompt (in the CLI) and stored solely in
the OS keyring under a single namespaced key. It is never written to TOML, env
files, SQLite, arguments, logs, exceptions, fixtures, or audit records. Reading
it registers it with the redaction engine so it is scrubbed from all output.
"""

from __future__ import annotations

from sobai.auth import CredentialStore
from sobai.core.errors import ConnectorError

TOKEN_KEY = "connector:notion:token"


class NotionAuth:
    def __init__(self, creds: CredentialStore) -> None:
        self._creds = creds

    def has_token(self) -> bool:
        return self._creds.has(TOKEN_KEY)

    def token(self) -> str:
        token = self._creds.get(TOKEN_KEY)  # also registers it for redaction
        if not token:
            raise ConnectorError("Notion is not connected.", hint="Run `sobai connect notion`.")
        return token

    def save_token(self, token: str) -> None:
        self._creds.set(TOKEN_KEY, token)

    def clear(self) -> bool:
        return self._creds.delete(TOKEN_KEY)
