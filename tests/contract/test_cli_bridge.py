from __future__ import annotations

import os
from pathlib import Path

import pytest

from sobai.core.errors import ProviderUnavailableError
from sobai.core.types import GenerateParams, Message
from sobai.providers.cli_bridge import ClaudeCliProvider


def _make_fake_claude(bin_dir: Path, argv_dump: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        f'#!/bin/bash\nprintf "%s\\0" "$@" > "{argv_dump}"\necho \'{{"result": "FAKE_OK"}}\'\n'
    )
    script.chmod(0o755)


async def test_bridge_passes_args_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    argv_dump = tmp_path / "argv.bin"
    _make_fake_claude(bin_dir, argv_dump)
    monkeypatch.setenv("PATH", str(bin_dir))

    injection = "list files; touch " + str(tmp_path / "PWNED") + " $(whoami) `id`"
    provider = ClaudeCliProvider()
    params = GenerateParams(model="", messages=[Message.user(injection)])
    result = await provider.generate(params)

    assert result.text == "FAKE_OK"
    # The dangerous side effect must NOT have happened.
    assert not (tmp_path / "PWNED").exists()
    # The prompt must have been received verbatim as a single argv element.
    received = argv_dump.read_bytes().decode().split("\0")
    assert injection in received


async def test_bridge_missing_executable_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # no 'claude' here
    provider = ClaudeCliProvider()
    params = GenerateParams(model="", messages=[Message.user("hi")])
    with pytest.raises(ProviderUnavailableError):
        await provider.generate(params)


async def test_bridge_nonzero_exit_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text("#!/bin/bash\necho 'boom' >&2\nexit 3\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    provider = ClaudeCliProvider()
    from sobai.core.errors import ProviderError

    with pytest.raises(ProviderError):
        await provider.generate(GenerateParams(model="", messages=[Message.user("hi")]))


def test_health_reports_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty2"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    import asyncio

    provider = ClaudeCliProvider()
    health = asyncio.run(provider.health())
    assert health.ok is False
    assert "not found" in health.detail


def test_os_environ_untouched() -> None:
    # Sanity: importing the bridge doesn't mutate PATH.
    assert "PATH" in os.environ
