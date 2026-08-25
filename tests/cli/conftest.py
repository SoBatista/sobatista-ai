"""Shared fixtures for the CLI suite: isolated state, the real entry point, raw SQL.

``cli`` drives ``sobai.cli.app.main`` — what a user actually runs — so exit
codes, redaction, and the stdout/stderr split are the real ones rather than the
Typer test runner's approximation. ``db_query`` reads the SQLite state file
directly, which is the only way to prove what was *stored* rather than what a
command chose to show.
"""

from __future__ import annotations

import io
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sobai.cli import app as app_module


@pytest.fixture
def sobai_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Isolate every application directory under tmp_path, in-process included."""
    values = {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
        # Rich wraps to the terminal width; keep lines intact so assertions can
        # match a whole answer that would otherwise be split across lines.
        "COLUMNS": "200",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


class FakeStdin:
    """A stdin stand-in that is either a pipe with contents or a terminal."""

    def __init__(self, data: bytes = b"", *, tty: bool = False) -> None:
        self.buffer = io.BytesIO(data)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def read(self) -> str:
        return self.buffer.getvalue().decode()


@dataclass(frozen=True, slots=True)
class CliOutcome:
    """The result of a real `sobai` invocation."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


@pytest.fixture
def cli(
    sobai_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Callable[..., CliOutcome]:
    """Run the real console entry point and capture its two streams separately."""

    def _run(argv: list[str], *, stdin: bytes | None = None) -> CliOutcome:
        # stdin=None means "a terminal", so a command that would read stdin
        # fails fast instead of consuming whatever the test runner attached.
        monkeypatch.setattr("sys.stdin", FakeStdin(stdin or b"", tty=stdin is None))
        previous = sys.argv
        sys.argv = ["sobai", *argv]
        code = 0
        try:
            app_module.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
        finally:
            sys.argv = previous
        captured = capsys.readouterr()
        return CliOutcome(exit_code=code, stdout=captured.out, stderr=captured.err)

    return _run


@pytest.fixture
def db_query(sobai_env: dict[str, str]) -> Callable[[str], list[dict[str, Any]]]:
    """Read the state database directly, treating "no database" as "no rows"."""

    def _query(sql: str) -> list[dict[str, Any]]:
        path = Path(sobai_env["SOBAI_DATA_DIR"]) / "state.db"
        if not path.exists():
            return []
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in conn.execute(sql)]
        finally:
            conn.close()

    return _query
