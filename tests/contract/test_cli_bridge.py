"""Tests for the hardened Claude Code / Codex CLI bridges."""

from __future__ import annotations

from pathlib import Path

import pytest

from sobai.core.errors import ProviderError, ProviderUnavailableError
from sobai.core.types import GenerateParams, Message
from sobai.providers.cli_bridge import (
    CLI_DEFAULT_MODEL,
    ClaudeCliProvider,
    CodexCliProvider,
)

CLAUDE_FLAGS = {
    "--print",
    "--output-format",
    "--tools",
    "--strict-mcp-config",
    "--mcp-config",
    "--safe-mode",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--setting-sources",
    "--append-system-prompt",
    "--model",
}
CODEX_FLAGS = {
    "--json",
    "--sandbox",
    "--ephemeral",
    "--skip-git-repo-check",
    "--cd",
    "--ignore-user-config",
    "--ignore-rules",
    "--config",
    "--output-last-message",
    "--model",
}

DANGEROUS = {
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--bare",
    "--dangerously-bypass-approvals-and-sandbox",
    "--yolo",
    "danger-full-access",
    "--approve-for-me",
    "--dangerously-bypass-hook-trust",
    "workspace-write",
}


def _params(model: str = CLI_DEFAULT_MODEL) -> GenerateParams:
    return GenerateParams(model=model, system="be careful", messages=[Message.user("hi there")])


# --------------------------------------------------------------------------- #
# argv building (pure) — security flags present, dangerous flags absent
# --------------------------------------------------------------------------- #
def test_claude_argv_security_flags() -> None:
    argv = ClaudeCliProvider()._build_argv("claude", _params(), CLAUDE_FLAGS, "/tmp/x")
    assert "--print" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--tools") + 1] == ""  # all built-in tools disabled
    assert "--strict-mcp-config" in argv
    assert '{"mcpServers":{}}' in argv
    assert "--safe-mode" in argv
    assert "--disable-slash-commands" in argv
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert not (set(argv) & DANGEROUS)
    # sentinel model must NOT be passed as --model default
    assert "--model" not in argv
    assert "default" not in argv


def test_claude_argv_real_model_passed() -> None:
    argv = ClaudeCliProvider()._build_argv("claude", _params("claude-x"), CLAUDE_FLAGS, "/tmp/x")
    assert argv[argv.index("--model") + 1] == "claude-x"


def test_claude_argv_omits_unsupported_flags() -> None:
    # Only required flags supported -> optional hardening flags omitted, no crash.
    minimal = {"--print", "--output-format", "--tools", "--strict-mcp-config", "--mcp-config"}
    argv = ClaudeCliProvider()._build_argv("claude", _params(), minimal, "/tmp/x")
    assert "--safe-mode" not in argv
    assert "--tools" in argv  # required boundary still there


def test_codex_argv_security_flags() -> None:
    argv = CodexCliProvider()._build_argv("codex", _params(), CODEX_FLAGS, "/tmp/x")
    assert argv[:2] == ["codex", "exec"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in argv
    assert "--skip-git-repo-check" in argv
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert argv[-1] == "-"  # prompt read from stdin
    assert "tools.web_search=false" in argv
    assert "mcp_servers={}" in argv
    assert not (set(argv) & DANGEROUS)
    assert "--model" not in argv


def test_codex_argv_real_model_passed() -> None:
    argv = CodexCliProvider()._build_argv("codex", _params("gpt-x"), CODEX_FLAGS, "/tmp/x")
    assert argv[argv.index("--model") + 1] == "gpt-x"


# --------------------------------------------------------------------------- #
# fail-closed when a required security flag is unsupported
# --------------------------------------------------------------------------- #
def test_claude_fail_closed_missing_flag() -> None:
    provider = ClaudeCliProvider()
    with pytest.raises(ProviderError, match="security"):
        provider._require_flags({"--print", "--output-format"})  # missing --tools etc.


def test_codex_fail_closed_missing_flag() -> None:
    provider = CodexCliProvider()
    with pytest.raises(ProviderError, match="security"):
        provider._require_flags({"--json"})  # missing --sandbox etc.


# --------------------------------------------------------------------------- #
# output parsing (pure)
# --------------------------------------------------------------------------- #
def test_claude_parse_output_usage_and_cost() -> None:
    stdout = (
        '{"result":"hello","usage":{"input_tokens":3,"output_tokens":5,'
        '"cache_read_input_tokens":2},"total_cost_usd":0.0012}'
    )
    completion = ClaudeCliProvider()._parse_output(stdout, cwd="/tmp/x", params=_params())
    assert completion.text == "hello"
    assert completion.usage.input_tokens == 3
    assert completion.usage.cached_input_tokens == 2
    assert completion.usage.cost_usd == 0.0012


def test_claude_parse_output_is_error_raises() -> None:
    with pytest.raises(ProviderError):
        ClaudeCliProvider()._parse_output(
            '{"is_error":true,"result":"boom"}', cwd="/tmp/x", params=_params()
        )


def test_codex_parse_output_jsonl(tmp_path: Path) -> None:
    stdout = (
        '{"type":"item.completed","item":{"type":"agent_message","text":"answer"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":8,'
        '"output_tokens":4}}\n'
    )
    completion = CodexCliProvider()._parse_output(stdout, cwd=str(tmp_path), params=_params())
    assert completion.text == "answer"
    assert completion.usage.input_tokens == 10
    assert completion.usage.cached_input_tokens == 8
    assert completion.usage.output_tokens == 4


# --------------------------------------------------------------------------- #
# integration via fake executables (prompt via stdin, never argv; no shell)
# --------------------------------------------------------------------------- #
def _write_fake_claude(bin_dir: Path, argv_file: Path, stdin_file: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/bash\n"
        'case "$*" in *--help*) echo "--print --output-format --tools --strict-mcp-config '
        "--mcp-config --model --append-system-prompt --safe-mode --disable-slash-commands "
        '--no-session-persistence --setting-sources"; exit 0;; esac\n'
        f'printf "%s\\0" "$@" > "{argv_file}"\n'
        f'cat > "{stdin_file}"\n'
        'echo \'{"result":"FAKE_OK","usage":{"input_tokens":3,"output_tokens":5,'
        '"cache_read_input_tokens":2},"total_cost_usd":0.0012}\'\n'
    )
    script.chmod(0o755)


async def test_claude_bridge_stdin_no_argv_no_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    argv_file = tmp_path / "argv.bin"
    stdin_file = tmp_path / "stdin.txt"
    _write_fake_claude(bin_dir, argv_file, stdin_file)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")

    injection = "list files; touch " + str(tmp_path / "PWNED") + " $(whoami) `id`"
    provider = ClaudeCliProvider()
    completion = await provider.generate(
        GenerateParams(model=CLI_DEFAULT_MODEL, system="sys", messages=[Message.user(injection)])
    )

    assert completion.text == "FAKE_OK"
    assert completion.usage.cost_usd == 0.0012
    assert not (tmp_path / "PWNED").exists()  # no shell interpolation happened
    argv_dump = argv_file.read_bytes().decode()
    stdin_dump = stdin_file.read_text()
    assert injection in stdin_dump  # prompt delivered via stdin
    assert injection not in argv_dump  # never on argv / process list
    assert "--tools" in argv_dump
    assert "default" not in argv_dump.split("\0")  # sentinel not passed


async def test_claude_bridge_missing_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(ProviderUnavailableError):
        await ClaudeCliProvider().generate(_params())


async def test_claude_bridge_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/bash\n"
        'case "$*" in *--help*) echo "--print --output-format --tools --strict-mcp-config '
        '--mcp-config"; exit 0;; esac\n'
        "echo boom >&2\nexit 2\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    with pytest.raises(ProviderError):
        await ClaudeCliProvider().generate(_params())


def test_bridge_strips_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-pass")
    env = ClaudeCliProvider()._bridge_env()
    assert "ANTHROPIC_API_KEY" not in env  # bridge uses subscription, not API billing
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-x")
    assert "OPENAI_API_KEY" not in CodexCliProvider()._bridge_env()
