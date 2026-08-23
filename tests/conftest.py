"""Shared pytest fixtures: isolated paths, an in-memory keyring, a CLI runner."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError
from typer.testing import CliRunner

from sobai.core.paths import Paths
from sobai.core.redaction import clear_registered_secrets


class MemoryKeyring(KeyringBackend):
    """A non-persistent keyring backend for tests (never touches the OS store)."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) in self._data:
            del self._data[(service, username)]
        else:
            raise PasswordDeleteError("not found")


@pytest.fixture(autouse=True)
def _clean_secrets() -> Iterator[None]:
    clear_registered_secrets()
    yield
    clear_registered_secrets()


@pytest.fixture
def mem_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """Point all app directories at a tmp dir via the env overrides."""
    monkeypatch.setenv("SOBAI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SOBAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOBAI_CACHE_DIR", str(tmp_path / "cache"))
    paths = Paths.resolve()
    paths.ensure()
    return paths


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()
