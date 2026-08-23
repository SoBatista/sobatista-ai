"""Credential storage backed by the OS keyring (Secret Service / libsecret)."""

from .keyring_store import CredentialStore, KeyringStatus

__all__ = ["CredentialStore", "KeyringStatus"]
