"""Tests for the subscription-first `sobai init` experience."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sobai.cli.app import app
from sobai.core.config import load_config
from sobai.core.paths import Paths
from sobai.providers import cli_status
from sobai.providers.cli_status import CliAuthStatus
from sobai.providers.registry import select_provider_model


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    monkeypatch.setenv("SOBAI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SOBAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOBAI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NO_COLOR", "1")
    return Paths.resolve()


def _status(name: str, *, installed=True, authed=False, mode=None, tier=None) -> CliAuthStatus:
    return CliAuthStatus(
        name=name,
        executable=name.split("-")[0],
        installed=installed,
        authenticated=authed,
        mode=mode,
        detail="detail",
        tier=tier,
    )


def _patch(monkeypatch, *, claude, codex, ollama, interactive=True) -> None:
    monkeypatch.setattr(cli_status, "detect_claude_cli", lambda: claude)
    monkeypatch.setattr(cli_status, "detect_codex_cli", lambda: codex)
    monkeypatch.setattr("sobai.cli.init._discover_ollama", lambda app: ollama)
    if interactive:
        monkeypatch.setattr("sobai.ui.console.UI.is_interactive", lambda self: True)


def _cfg(env: Paths):  # type: ignore[no-untyped-def]
    return load_config(env)


# --------------------------------------------------------------------------- #
def test_select_codex_subscription(runner: CliRunner, env, monkeypatch) -> None:
    _patch(
        monkeypatch,
        claude=_status("claude-cli", authed=True, mode="subscription"),
        codex=_status("codex-cli", authed=True, mode="subscription"),
        ollama=[],
    )
    # Menu: 1 Codex, 2 Claude, 3 direct API. Choose 1.
    result = runner.invoke(app, ["init"], env=None, input="1\n")
    assert result.exit_code == 0, result.output
    cfg = _cfg(env)
    assert cfg.active_provider == "codex-cli"
    assert cfg.active_model == "codex-subscription"
    assert cfg.models["codex-subscription"] == "codex-cli:default"
    # both subscription aliases seeded because both authenticated
    assert cfg.models["claude-subscription"] == "claude-cli:default"
    # the default sentinel resolves without inventing a model id
    assert select_provider_model(cfg) == ("codex-cli", "default")


def test_select_claude_subscription(runner: CliRunner, env, monkeypatch) -> None:
    _patch(
        monkeypatch,
        claude=_status("claude-cli", authed=True, mode="subscription", tier="max"),
        codex=_status("codex-cli", installed=False),
        ollama=[],
    )
    # Menu: 1 Claude, 2 direct API. Choose 1.
    result = runner.invoke(app, ["init"], input="1\n")
    assert result.exit_code == 0, result.output
    cfg = _cfg(env)
    assert cfg.active_provider == "claude-cli"
    assert cfg.active_model == "claude-subscription"


def test_configure_direct_api(runner: CliRunner, env, monkeypatch, mem_keyring) -> None:
    _patch(
        monkeypatch,
        claude=_status("claude-cli", installed=False),
        codex=_status("codex-cli", installed=False),
        ollama=[],
    )
    # Only option is "Configure direct API access" (1) -> Anthropic (1) -> key -> blank model.
    result = runner.invoke(app, ["init"], input="1\n1\nsk-ant-testkey123\n\n")
    assert result.exit_code == 0, result.output
    from sobai.auth import CredentialStore

    assert CredentialStore().has("provider:anthropic:api_key")
    assert _cfg(env).active_provider == "anthropic"


def test_login_cancellation(runner: CliRunner, env, monkeypatch) -> None:
    _patch(
        monkeypatch,
        claude=_status("claude-cli", installed=True, authed=False),
        codex=_status("codex-cli", installed=False),
        ollama=[],
    )
    # Menu: 1 "Log in to Claude", 2 direct API. Choose login (1), then decline (n).
    result = runner.invoke(app, ["init"], input="1\nn\n")
    assert result.exit_code == 0, result.output
    assert _cfg(env).active_provider is None  # login declined -> nothing selected


def test_login_failure(runner: CliRunner, env, monkeypatch) -> None:
    _patch(
        monkeypatch,
        claude=_status("claude-cli", installed=True, authed=False),
        codex=_status("codex-cli", installed=False),
        ollama=[],
    )
    monkeypatch.setattr("sobai.cli.init.shutil.which", lambda _e: "/usr/bin/claude")
    monkeypatch.setattr(
        "sobai.cli.init.subprocess.run", lambda *a, **k: SimpleNamespace(returncode=1)
    )
    result = runner.invoke(app, ["init"], input="1\ny\n")
    assert result.exit_code == 0, result.output
    assert _cfg(env).active_provider is None  # login failed -> unchanged


def test_non_interactive_prefers_subscription_no_login(runner: CliRunner, env, monkeypatch) -> None:
    # Do NOT patch is_interactive -> CliRunner is non-interactive.
    _patch(
        monkeypatch,
        claude=_status("claude-cli", authed=True, mode="subscription"),
        codex=_status("codex-cli", authed=True, mode="subscription"),
        ollama=[],
        interactive=False,
    )

    def _boom(*a, **k):  # login must never be launched non-interactively
        raise AssertionError("subprocess.run must not be called in non-interactive init")

    monkeypatch.setattr("sobai.cli.init.subprocess.run", _boom)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    cfg = _cfg(env)
    assert cfg.active_provider == "codex-cli"  # subscription preferred, no login launched
    assert cfg.models["codex-subscription"] == "codex-cli:default"


def test_idempotent_and_preserves_user_config(runner: CliRunner, env, monkeypatch) -> None:
    _patch(
        monkeypatch,
        claude=_status("claude-cli", installed=False),
        codex=_status("codex-cli", authed=True, mode="subscription"),
        ollama=[],
        interactive=False,
    )
    runner.invoke(app, ["init"])
    # user adds a custom alias + profile
    store = load_config(env)
    store.models["myalias"] = "ollama:custom:7b"
    from sobai.core.config import save_config

    save_config(store, env)
    # run init again
    runner.invoke(app, ["init"])
    cfg = _cfg(env)
    assert cfg.models["myalias"] == "ollama:custom:7b"  # preserved
    assert cfg.models["codex-subscription"] == "codex-cli:default"  # unchanged


def test_empty_config_migration(runner: CliRunner, env, monkeypatch) -> None:
    # No config file exists yet; init on a machine with only Ollama.
    _patch(
        monkeypatch,
        claude=_status("claude-cli", installed=False),
        codex=_status("codex-cli", installed=False),
        ollama=["qwen2.5-coder:7b"],
        interactive=False,
    )
    assert not env.config_file.exists()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    cfg = _cfg(env)
    assert cfg.active_provider == "ollama"
    assert "qwen7b" in cfg.models
