"""Credential storage backed by the OS keyring.

All secrets — provider API keys, OAuth client secrets, OAuth token bundles,
connector tokens — live here, never in TOML, environment files, shell history,
or subprocess arguments. Keys are namespaced under a single service so a user
can audit every SoBatista AI secret in their keyring under one name.

Any secret read back is immediately registered with the redaction engine so it
can never leak into logs or output for the remainder of the process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import keyring
from keyring.errors import KeyringError

from sobai.core.errors import AuthError
from sobai.core.redaction import register_secret

SERVICE = "sobai"


@dataclass(frozen=True, slots=True)
class KeyringStatus:
    """Diagnostic snapshot of the active keyring backend, for ``sobai doctor``."""

    backend: str
    usable: bool
    detail: str


def _null_backend() -> bool:
    """True when keyring resolved to the no-op 'fail' backend (no secret store)."""
    backend = keyring.get_keyring()
    return type(backend).__module__.endswith("backends.fail")


class CredentialStore:
    """Namespaced wrapper over the OS keyring with JSON bundle support."""

    def __init__(self, service: str = SERVICE) -> None:
        self._service = service

    # -- diagnostics -------------------------------------------------------
    def status(self) -> KeyringStatus:
        try:
            backend = keyring.get_keyring()
            name = f"{type(backend).__module__}.{type(backend).__name__}"
            if _null_backend():
                return KeyringStatus(
                    backend=name,
                    usable=False,
                    detail="No usable secret store found. On Linux install a Secret "
                    "Service provider (e.g. gnome-keyring / KWallet) and unlock it.",
                )
            return KeyringStatus(backend=name, usable=True, detail="ok")
        except KeyringError as exc:  # pragma: no cover - environment dependent
            return KeyringStatus(backend="unknown", usable=False, detail=str(exc))

    def _require_backend(self) -> None:
        if _null_backend():
            raise AuthError(
                "No usable OS keyring backend is available.",
                hint="Install and unlock a Secret Service provider "
                "(gnome-keyring, KWallet, or equivalent), then retry. "
                "Run `sobai doctor` to diagnose.",
            )

    # -- raw string secrets ------------------------------------------------
    def get(self, key: str) -> str | None:
        # Reading when no secret store is available means "nothing stored" — a
        # read-only command (providers list, doctor, connections) must not fail
        # just because there is no keyring. Writes still fail closed (see set()).
        if _null_backend():
            return None
        try:
            value = keyring.get_password(self._service, key)
        except KeyringError:
            return None
        if value is not None:
            register_secret(value)
        return value

    def set(self, key: str, value: str) -> None:
        self._require_backend()
        register_secret(value)
        try:
            keyring.set_password(self._service, key, value)
        except KeyringError as exc:
            raise AuthError(f"Failed to store secret '{key}' in keyring: {exc}") from exc

    def delete(self, key: str) -> bool:
        try:
            keyring.delete_password(self._service, key)
            return True
        except keyring.errors.PasswordDeleteError:
            return False
        except KeyringError as exc:
            raise AuthError(f"Failed to delete secret '{key}' from keyring: {exc}") from exc

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    # -- structured (JSON) bundles ----------------------------------------
    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(f"Stored secret '{key}' is corrupt (not valid JSON): {exc}") from exc
        # Register any string leaf values so token fields are also redacted.
        for v in data.values():
            if isinstance(v, str):
                register_secret(v)
        return data

    def set_json(self, key: str, value: dict[str, Any]) -> None:
        for v in value.values():
            if isinstance(v, str):
                register_secret(v)
        self.set(key, json.dumps(value))
