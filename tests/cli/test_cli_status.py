"""Tests for subscription-CLI authentication detection (mocked subprocesses)."""

from __future__ import annotations

import json

import pytest

from sobai.providers import cli_status


@pytest.fixture
def fake_which(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def _set(name: str | None) -> None:
        monkeypatch.setattr(cli_status.shutil, "which", lambda _exe: name)

    return _set


def _set_run(monkeypatch: pytest.MonkeyPatch, result: tuple[int, str, str]) -> None:
    monkeypatch.setattr(cli_status, "_run", lambda argv, timeout=15.0: result)


# -- claude ---------------------------------------------------------------- #
def test_claude_not_installed(monkeypatch, fake_which) -> None:
    fake_which(None)
    st = cli_status.detect_claude_cli()
    assert not st.installed and not st.authenticated and st.mode is None


def test_claude_subscription_json(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/claude")
    body = json.dumps(
        {
            "loggedIn": True,
            "authMethod": "claude.ai",
            "subscriptionType": "max",
            "email": "user@example.com",
            "orgName": "secret org",
        }
    )
    _set_run(monkeypatch, (0, body, ""))
    st = cli_status.detect_claude_cli()
    assert st.authenticated and st.mode == "subscription"
    assert st.tier == "max"
    assert "subscription" in st.detail and "max" in st.detail
    # identity must never leak into the displayed detail
    assert "user@example.com" not in st.detail
    assert "secret org" not in st.detail


def test_claude_api_key_json(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/claude")
    body = json.dumps({"loggedIn": True, "authMethod": "apiKey", "apiProvider": "firstParty"})
    _set_run(monkeypatch, (0, body, ""))
    st = cli_status.detect_claude_cli()
    assert st.authenticated and st.mode == "api-key"
    assert st.tier is None


def test_claude_not_logged_in(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/claude")
    _set_run(monkeypatch, (0, json.dumps({"loggedIn": False}), ""))
    st = cli_status.detect_claude_cli()
    assert not st.authenticated


def test_claude_timeout(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/claude")
    _set_run(monkeypatch, (124, "", "timed out"))
    st = cli_status.detect_claude_cli()
    assert st.installed and not st.authenticated and st.mode == "unknown"
    assert "timed out" in st.detail


def test_claude_text_fallback(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/claude")
    _set_run(monkeypatch, (0, "You are logged in.", ""))
    st = cli_status.detect_claude_cli()
    assert st.authenticated and st.mode == "subscription"


def test_claude_error_exit(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/claude")
    _set_run(monkeypatch, (1, "", "Not logged in"))
    st = cli_status.detect_claude_cli()
    assert not st.authenticated


# -- codex ----------------------------------------------------------------- #
def test_codex_not_installed(monkeypatch, fake_which) -> None:
    fake_which(None)
    st = cli_status.detect_codex_cli()
    assert not st.installed


def test_codex_chatgpt(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/codex")
    _set_run(monkeypatch, (0, "Logged in using ChatGPT", ""))
    st = cli_status.detect_codex_cli()
    assert st.authenticated and st.mode == "subscription"
    assert "ChatGPT" in st.detail


def test_codex_api_key(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/codex")
    _set_run(monkeypatch, (0, "Logged in using API key", ""))
    st = cli_status.detect_codex_cli()
    assert st.mode == "api-key"


def test_codex_not_logged_in(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/codex")
    _set_run(monkeypatch, (1, "Not logged in", ""))
    st = cli_status.detect_codex_cli()
    assert not st.authenticated and st.mode is None


def test_codex_timeout(monkeypatch, fake_which) -> None:
    fake_which("/usr/bin/codex")
    _set_run(monkeypatch, (124, "", ""))
    st = cli_status.detect_codex_cli()
    assert st.mode == "unknown"
