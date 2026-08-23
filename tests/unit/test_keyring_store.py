from __future__ import annotations

from sobai.auth import CredentialStore
from sobai.core.redaction import REDACTED, redact


def test_set_get_delete(mem_keyring) -> None:
    store = CredentialStore()
    assert store.get("provider:anthropic:api_key") is None
    store.set("provider:anthropic:api_key", "sekret-value-abc123")
    assert store.get("provider:anthropic:api_key") == "sekret-value-abc123"
    assert store.has("provider:anthropic:api_key")
    assert store.delete("provider:anthropic:api_key") is True
    assert store.delete("provider:anthropic:api_key") is False


def test_get_registers_for_redaction(mem_keyring) -> None:
    store = CredentialStore()
    store.set("k", "topsecretcredential42")
    # A freshly loaded value must be scrubbed from later output.
    store.get("k")
    assert "topsecretcredential42" not in redact("leak topsecretcredential42")
    assert REDACTED in redact("leak topsecretcredential42")


def test_json_bundle_roundtrip(mem_keyring) -> None:
    store = CredentialStore()
    bundle = {"access_token": "atk-123456", "refresh_token": "rtk-abcdef"}
    store.set_json("connector:youtube:token", bundle)
    loaded = store.get_json("connector:youtube:token")
    assert loaded == bundle
    # token leaves are redacted after load
    assert "atk-123456" not in redact("x atk-123456")


def test_status_reports_usable(mem_keyring) -> None:
    status = CredentialStore().status()
    assert status.usable is True
