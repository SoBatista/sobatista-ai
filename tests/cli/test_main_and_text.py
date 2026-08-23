"""Exercise the process entry point (main) and text-mode rendering paths."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sobai.cli import app as app_module
from sobai.cli.app import app
from sobai.core.errors import ExitCode


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    e = {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
    }
    for k, v in e.items():
        monkeypatch.setenv(k, v)
    return e


def _run_main(argv: list[str]) -> int:
    old = sys.argv
    sys.argv = ["sobai", *argv]
    try:
        app_module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = old
    return 0


def test_main_version(env: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    code = _run_main(["--version"])
    assert code == 0
    assert "sobai" in capsys.readouterr().out


def test_main_local_only_exit_code(env: dict[str, str]) -> None:
    code = _run_main(["--local-only", "-p", "anthropic", "-m", "anthropic:x", "ask", "hi"])
    assert code == int(ExitCode.POLICY)


def test_main_json_error_output(env: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    code = _run_main(["--json", "--local-only", "-p", "anthropic", "-m", "anthropic:x", "ask", "x"])
    assert code == int(ExitCode.POLICY)
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "LocalOnlyViolation"


def test_main_usage_error(env: dict[str, str]) -> None:
    code = _run_main(["definitely-not-a-command"])
    assert code != 0


def test_main_missing_model_config_error(env: dict[str, str]) -> None:
    code = _run_main(["-p", "anthropic", "ask", "hi"])
    assert code == int(ExitCode.CONFIG)


# -- text-mode rendering paths --------------------------------------------- #
def test_history_empty_text(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["history"], env=env)
    assert r.exit_code == 0
    assert "No runs" in r.output


def test_audit_empty_text(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["audit"], env=env)
    assert r.exit_code == 0


def test_models_list_empty_text(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["models", "list"], env=env)
    assert r.exit_code == 0
    assert "No model aliases" in r.output


def test_privacy_explain_text(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["privacy", "explain"], env=env)
    assert r.exit_code == 0
    assert "keyring" in r.output.lower()


def test_config_show_raw(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["config", "show", "--raw"], env=env)
    assert r.exit_code == 0
    assert "[providers" in r.output


def test_runs_show_missing(runner: CliRunner, env: dict[str, str]) -> None:
    from sobai.core.errors import NotFoundError

    r = runner.invoke(app, ["runs", "show", "deadbeef"], env=env)
    assert r.exit_code != 0
    assert isinstance(r.exception, NotFoundError)
