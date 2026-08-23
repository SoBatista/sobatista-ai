"""Tests for the safe canonical `sobai update` command (mocked subprocesses)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sobai.cli import update_cmd
from sobai.cli.aliases import _render
from sobai.cli.app import app
from sobai.core.config import load_config
from sobai.core.errors import ConfigError, NotFoundError
from sobai.core.paths import Paths
from sobai.storage import Database

UV = "/usr/bin/uv"
SOBAI = "/usr/bin/sobai"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    monkeypatch.setenv("SOBAI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SOBAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOBAI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NO_COLOR", "1")
    return Paths.resolve()


def _make_checkout(base: Path, name: str = "co", version: str = "9.9.9") -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "pyproject.toml").write_text(f'[project]\nname = "sobatista-ai"\nversion = "{version}"\n')
    return d


class Recorder:
    """Records argv calls; returns canned results keyed by the argv contents."""

    def __init__(
        self,
        *,
        build_rc=0,
        install_rc=0,
        verify_rc=0,
        verify_out="sobai 9.9.9",
        build_err="",
        install_err="",
    ):
        self.calls: list[list[str]] = []
        self.build_rc, self.install_rc, self.verify_rc = build_rc, install_rc, verify_rc
        self.verify_out, self.build_err, self.install_err = verify_out, build_err, install_err

    def __call__(self, argv, *, timeout, cwd=None):  # type: ignore[no-untyped-def]
        self.calls.append(list(argv))
        if "build" in argv:
            return (self.build_rc, "", self.build_err)
        if "install" in argv:
            return (self.install_rc, "", self.install_err)
        if "--version" in argv:
            return (self.verify_rc, self.verify_out, "")
        return (0, "", "")

    def ran(self, needle: str) -> bool:
        return any(needle in c for c in self.calls)


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def _apply(rec: Recorder, *, uv: str | None = UV, sobai: str | None = SOBAI) -> Recorder:
        monkeypatch.setattr(update_cmd, "_run", rec)
        monkeypatch.setattr(
            update_cmd.shutil,
            "which",
            lambda exe: {"uv": uv, "sobai": sobai}.get(exe),
        )
        return rec

    return _apply


# --------------------------------------------------------------------------- #
# validate_source (pure)
# --------------------------------------------------------------------------- #
def test_validate_source_ok(tmp_path: Path) -> None:
    co = _make_checkout(tmp_path, version="1.2.3")
    abs_path, version = update_cmd.validate_source(str(co))
    assert abs_path == co.resolve()
    assert version == "1.2.3"


def test_validate_source_missing(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        update_cmd.validate_source(str(tmp_path / "nope"))


def test_validate_source_no_pyproject(tmp_path: Path) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ConfigError):
        update_cmd.validate_source(str(d))


def test_validate_source_wrong_project(tmp_path: Path) -> None:
    d = tmp_path / "other"
    d.mkdir()
    (d / "pyproject.toml").write_text('[project]\nname = "something-else"\nversion = "1"\n')
    with pytest.raises(ConfigError, match="sobatista-ai"):
        update_cmd.validate_source(str(d))


def test_validate_source_refuses_root() -> None:
    with pytest.raises(ConfigError, match="overly broad"):
        update_cmd.validate_source("/")


# --------------------------------------------------------------------------- #
# update flow (mocked subprocess)
# --------------------------------------------------------------------------- #
def test_update_with_source_yes(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    rec = patched(Recorder())
    r = runner.invoke(app, ["--json", "update", "--source", str(co), "--yes"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["status"] == "updated" and data["verified"] is True
    # stored for reuse
    assert load_config(env).update_source == str(co.resolve())
    # argv safety: install used argv array with the literal absolute path
    assert [UV, "tool", "install", "--force", str(co.resolve())] in rec.calls
    # build happened before install
    assert rec.ran("build")


def test_update_reuses_stored_source(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    patched(Recorder())
    runner.invoke(app, ["update", "--source", str(co), "--yes"])
    # second run without --source reuses the stored path
    rec2 = patched(Recorder())
    r = runner.invoke(app, ["--json", "update", "--yes"])
    assert r.exit_code == 0, r.output
    assert rec2.ran("install")


def test_update_no_source_configured(runner: CliRunner, env, patched) -> None:
    patched(Recorder())
    r = runner.invoke(app, ["update", "--yes"])
    assert r.exit_code != 0
    assert isinstance(r.exception, ConfigError)


def test_update_path_with_spaces_and_metachars(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path, name="we ird; $(touch PWNED) `id`")
    rec = patched(Recorder())
    r = runner.invoke(app, ["update", "--source", str(co), "--yes"])
    assert r.exit_code == 0, r.output
    assert not (tmp_path / "PWNED").exists()  # never shell-interpreted
    # the exact path is a single argv element, unquoted/unescaped
    assert any(str(co.resolve()) in c for c in rec.calls)


def test_update_confirm_declined(runner: CliRunner, env, patched, tmp_path, monkeypatch) -> None:
    co = _make_checkout(tmp_path)
    rec = patched(Recorder())
    monkeypatch.setattr("sobai.ui.console.UI.is_interactive", lambda self: True)
    r = runner.invoke(app, ["update", "--source", str(co)], input="n\n")
    assert r.exit_code != 0
    from sobai.core.errors import OperationDeclined

    assert isinstance(r.exception, OperationDeclined)
    assert not rec.ran("install")  # nothing installed


def test_update_confirm_accepted(runner: CliRunner, env, patched, tmp_path, monkeypatch) -> None:
    co = _make_checkout(tmp_path)
    rec = patched(Recorder())
    monkeypatch.setattr("sobai.ui.console.UI.is_interactive", lambda self: True)
    r = runner.invoke(app, ["update", "--source", str(co)], input="y\n")
    assert r.exit_code == 0, r.output
    assert rec.ran("install")


def test_update_non_interactive_requires_yes(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    patched(Recorder())
    # CliRunner is non-interactive; without --yes it must decline, not hang.
    r = runner.invoke(app, ["update", "--source", str(co)])
    assert r.exit_code != 0
    from sobai.core.errors import OperationDeclined

    assert isinstance(r.exception, OperationDeclined)


def test_update_missing_uv(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    patched(Recorder(), uv=None)
    r = runner.invoke(app, ["update", "--source", str(co), "--yes"])
    assert r.exit_code != 0
    from sobai.core.errors import DependencyError

    assert isinstance(r.exception, DependencyError)


def test_update_build_failure_does_not_install(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    rec = patched(Recorder(build_rc=1, build_err="boom sk-ant-secretkey123 boom"))
    r = runner.invoke(app, ["update", "--source", str(co), "--yes"])
    assert r.exit_code != 0
    from sobai.core.errors import BuildError

    assert isinstance(r.exception, BuildError)
    assert not rec.ran("install")  # installed tool untouched
    assert "sk-ant-secretkey123" not in str(r.exception)  # redacted


def test_update_install_failure(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    patched(Recorder(install_rc=1))
    r = runner.invoke(app, ["update", "--source", str(co), "--yes"])
    assert r.exit_code != 0
    from sobai.core.errors import UpdateError

    assert isinstance(r.exception, UpdateError)


def test_update_verify_failure(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    patched(Recorder(verify_rc=1, verify_out=""))
    r = runner.invoke(app, ["update", "--source", str(co), "--yes"])
    assert r.exit_code != 0
    from sobai.core.errors import UpdateError

    assert isinstance(r.exception, UpdateError)


def test_update_timeout(runner: CliRunner, env, patched, tmp_path, monkeypatch) -> None:
    co = _make_checkout(tmp_path)
    from sobai.core.errors import OperationTimeout

    def _timeout(argv, *, timeout, cwd=None):  # type: ignore[no-untyped-def]
        raise OperationTimeout("timed out")

    patched(Recorder())
    monkeypatch.setattr(update_cmd, "_run", _timeout)
    r = runner.invoke(app, ["update", "--source", str(co), "--yes"])
    assert r.exit_code != 0
    assert isinstance(r.exception, OperationTimeout)


def test_update_no_git_or_network_commands(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    rec = patched(Recorder())
    runner.invoke(app, ["update", "--source", str(co), "--yes"])
    flat = [tok for call in rec.calls for tok in call]
    for forbidden in ("git", "pull", "fetch", "clone", "curl", "wget"):
        assert forbidden not in flat
    # only uv and the sobai executable are ever invoked
    assert all(call[0] in (UV, SOBAI) for call in rec.calls)


def test_update_no_modification_on_invalid_source(
    runner: CliRunner, env, patched, tmp_path
) -> None:
    rec = patched(Recorder())
    bad = tmp_path / "bad"
    bad.mkdir()  # no pyproject
    r = runner.invoke(app, ["update", "--source", str(bad), "--yes"])
    assert r.exit_code != 0
    assert not rec.calls  # nothing ran
    assert load_config(env).update_source is None  # config untouched


def test_update_audit_recorded(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    patched(Recorder())
    runner.invoke(app, ["update", "--source", str(co), "--yes"])
    db = Database(env.state_db)
    events = [e for e in db.list_audit() if e["event"] == "self_update"]
    db.close()
    assert events


def test_update_quiet_mode(runner: CliRunner, env, patched, tmp_path) -> None:
    co = _make_checkout(tmp_path)
    patched(Recorder())
    r = runner.invoke(app, ["--quiet", "update", "--source", str(co), "--yes"])
    assert r.exit_code == 0, r.output


# --------------------------------------------------------------------------- #
# --check delegation
# --------------------------------------------------------------------------- #
def test_update_check_delegates(runner: CliRunner, env, patched, monkeypatch) -> None:
    called = {"n": 0}

    def _fake_check(ctx):  # type: ignore[no-untyped-def]
        called["n"] += 1

    rec = patched(Recorder())
    monkeypatch.setattr("sobai.cli.app.update_check", _fake_check)
    r = runner.invoke(app, ["update", "--check"])
    assert r.exit_code == 0, r.output
    assert called["n"] == 1
    assert not rec.calls  # no build/install on --check
    assert load_config(env).update_source is None  # nothing changed


# --------------------------------------------------------------------------- #
# wrapper generation (bash/zsh/fish)
# --------------------------------------------------------------------------- #
def test_wrapper_bash_zsh_update_forwards_options() -> None:
    for shell in ("bash", "zsh"):
        content = _render(shell)
        assert 'sobai-update() {\n    command sobai update "$@"\n}' in content
        assert "eval" not in content
        # options wrapper must NOT insert `--` (that would break --check/--source)
        assert "command sobai update -- " not in content


def test_wrapper_fish_update_forwards_options() -> None:
    content = _render("fish")
    assert "function sobai-update\n    command sobai update $argv\nend" in content
    assert "update -- $argv" not in content
    assert "eval" not in content
