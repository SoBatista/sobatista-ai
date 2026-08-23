from __future__ import annotations

import pytest

from sobai.auth import CredentialStore
from sobai.connectors.notion.auth import TOKEN_KEY, NotionAuth
from sobai.core.errors import ConnectorError
from sobai.core.redaction import REDACTED, redact


def test_token_stored_keyring_only_and_redacted(mem_keyring) -> None:
    auth = NotionAuth(CredentialStore())
    assert not auth.has_token()
    auth.save_token("secret_ntn_TOKENVALUE1234567890")
    assert auth.has_token()
    assert auth.token() == "secret_ntn_TOKENVALUE1234567890"
    # reading the token registers it for redaction everywhere
    assert "secret_ntn_TOKENVALUE1234567890" not in redact("leak secret_ntn_TOKENVALUE1234567890")
    assert REDACTED in redact("leak secret_ntn_TOKENVALUE1234567890")


def test_token_key_namespaced() -> None:
    assert TOKEN_KEY == "connector:notion:token"


def test_token_missing_raises(mem_keyring) -> None:
    with pytest.raises(ConnectorError):
        NotionAuth(CredentialStore()).token()


def test_clear_removes(mem_keyring) -> None:
    auth = NotionAuth(CredentialStore())
    auth.save_token("secret_abc123456789")
    assert auth.clear() is True
    assert not auth.has_token()
