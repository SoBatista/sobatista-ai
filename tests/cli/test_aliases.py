from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sobai.cli.aliases import _render
from sobai.cli.app import app


def test_bash_wrappers_are_safe() -> None:
    content = _render("bash")
    # Uses safe argument forwarding, never eval, and the canonical command.
    assert "command sobai" in content
    assert '"$@"' in content
    assert "eval" not in content
    for name in ("yb-claude", "yb-cx", "notion-claude", "notion-cx"):
        assert name in content


def test_fish_wrappers_use_argv() -> None:
    content = _render("fish")
    assert "$argv" in content
    assert "function yb-claude" in content
    assert "eval" not in content


def test_install_writes_file(tmp_path: Path, runner: CliRunner) -> None:
    env = {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
    }
    result = runner.invoke(app, ["aliases", "install", "zsh"], env=env)
    assert result.exit_code == 0
    written = (tmp_path / "config" / "aliases.zsh").read_text()
    assert '"$@"' in written
    assert "eval" not in written


def test_unsupported_shell(tmp_path: Path, runner: CliRunner) -> None:
    env = {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
    }
    result = runner.invoke(app, ["aliases", "install", "powershell"], env=env)
    assert result.exit_code != 0
