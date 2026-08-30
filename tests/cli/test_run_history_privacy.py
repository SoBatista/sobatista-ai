"""Run history and the audit log describe a run; they never quote it.

Development builds before 0.2.0 recorded ``summary=text[:200]``, which put the
opening of every question into long-lived local state where `sobai history`,
`sobai runs show`, and anything else that reads the database could see it. These
tests submit a sentinel prompt and then look at the stored bytes directly —
what a command chooses to *display* is not evidence about what was *kept*.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from sobai.cli import session as session_mod
from sobai.cli.common import PromptText, history_summary
from sobai.core.context import AppContext, GlobalOptions
from sobai.core.errors import ExitCode, ProviderError
from sobai.core.types import (
    Completion,
    GenerateParams,
    StopReason,
    StreamEvent,
    StreamEventType,
    Usage,
)
from sobai.providers.base import Provider, ProviderHealth
from sobai.storage import Database

Cli = Callable[..., Any]
Query = Callable[[str], list[dict[str, Any]]]

#: A prompt whose every word is distinctive, so any leak is unambiguous. No
#: token collides with the metadata a run legitimately records.
SENTINEL = "zebra quartz verandah pineapple marzipan diagnosis"
SENTINEL_TOKENS = tuple(word for word in SENTINEL.split() if len(word) >= 4)


def assert_sentinel_absent(blob: str, *, where: str) -> None:
    """Fail if the sentinel, or any meaningful word of it, appears in *blob*."""
    lowered = blob.lower()
    assert SENTINEL not in lowered, f"the whole prompt is present in {where}"
    for token in SENTINEL_TOKENS:
        assert token not in lowered, f"{token!r} from the prompt is present in {where}"


class RecordingProvider(Provider):
    """A local provider that answers without echoing the question back."""

    name = "ollama"
    is_local = True

    def __init__(self, *, text: str = "an answer", fail: Exception | None = None) -> None:
        self._text = text
        self._fail = fail
        self.prompts: list[str] = []

    async def generate(self, params: GenerateParams) -> Completion:
        self.prompts.append(params.messages[-1].text())
        if self._fail:
            raise self._fail
        return Completion(
            text=self._text,
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=12, output_tokens=4),
            model=params.model,
        )

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        completion = await self.generate(params)
        yield StreamEvent(type=StreamEventType.TEXT, text=completion.text)
        yield StreamEvent(type=StreamEventType.DONE, completion=completion)

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> RecordingProvider:
    fake = RecordingProvider()
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: fake)
    return fake


def ask_sentinel(cli: Cli, *extra: str) -> Any:
    return cli(["-p", "ollama", "-m", "ollama:x", "ask", *extra, SENTINEL])


# --------------------------------------------------------------------------- #
# the summary itself
# --------------------------------------------------------------------------- #
def test_summary_describes_shape_and_nothing_else() -> None:
    summary = history_summary("ask", PromptText(text="olá mundo", source="argument"))
    assert summary == "ask · argument · 10 bytes · 9 chars"  # UTF-8 bytes, not characters
    assert_sentinel_absent(
        history_summary("ask", PromptText(SENTINEL, "argument")), where="summary"
    )


def test_no_start_run_call_site_records_prompt_content() -> None:
    """Every ``start_run`` summary must come from a content-free helper.

    A source-level check, because the mistake this guards against is a one-line
    convenience (``summary=text[:200]``) that reads harmlessly at the call site.
    """
    allowed = {"history_summary", "run_summary"}
    checked = 0
    for path in sorted(Path("src/sobai").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "start_run":
                continue
            summaries = [kw.value for kw in node.keywords if kw.arg == "summary"]
            for value in summaries:
                checked += 1
                assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name), (
                    f"{path}:{value.lineno} passes a raw expression as the run summary"
                )
                assert value.func.id in allowed, (
                    f"{path}:{value.lineno} builds its summary with "
                    f"{value.func.id!r}, not one of {sorted(allowed)}"
                )
    assert checked >= 5, "expected every model-backed command to record a summary"


# --------------------------------------------------------------------------- #
# what is stored
# --------------------------------------------------------------------------- #
def test_ask_stores_no_part_of_the_prompt(
    cli: Cli, provider: RecordingProvider, db_query: Query
) -> None:
    result = ask_sentinel(cli)
    assert result.exit_code == 0, result.output
    assert provider.prompts and SENTINEL in provider.prompts[0]  # it really was sent

    runs = db_query("SELECT * FROM runs")
    assert len(runs) == 1
    assert_sentinel_absent(json.dumps(runs), where="the runs table")
    assert runs[0]["summary"] == f"ask · argument · {len(SENTINEL)} bytes · {len(SENTINEL)} chars"


def test_ask_stores_no_audit_content(
    cli: Cli, provider: RecordingProvider, db_query: Query
) -> None:
    assert ask_sentinel(cli).exit_code == 0
    assert_sentinel_absent(json.dumps(db_query("SELECT * FROM audit")), where="the audit table")


def test_answer_text_is_not_stored(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, db_query: Query
) -> None:
    """Output is as sensitive as input, and is not persisted either."""
    monkeypatch.setattr(
        "sobai.cli.common.build_provider",
        lambda *a, **k: RecordingProvider(text="OUTPUT-SENTINEL-9"),
    )
    assert cli(["-p", "ollama", "-m", "ollama:x", "ask", "hi"]).exit_code == 0
    stored = json.dumps(db_query("SELECT * FROM runs") + db_query("SELECT * FROM audit"))
    assert "OUTPUT-SENTINEL-9" not in stored


def test_piped_prompt_records_its_source_only(
    cli: Cli, provider: RecordingProvider, db_query: Query
) -> None:
    result = cli(["-p", "ollama", "-m", "ollama:x", "ask"], stdin=SENTINEL.encode())
    assert result.exit_code == 0, result.output
    summary = db_query("SELECT * FROM runs")[0]["summary"]
    assert summary == f"ask · stdin · {len(SENTINEL)} bytes · {len(SENTINEL)} chars"
    assert_sentinel_absent(summary, where="the summary")


def test_session_turn_stores_no_prompt(
    sobai_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, db_query: Query
) -> None:
    monkeypatch.setattr(session_mod, "build_provider", lambda *a, **k: RecordingProvider())
    lines = iter([SENTINEL])

    def _read(_prompt: str) -> str:
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    app = AppContext.build(GlobalOptions(provider="ollama", model="ollama:x"))
    try:
        session_mod.InteractiveSession(app).run(_read)
    finally:
        app.close()
    runs = db_query("SELECT * FROM runs")
    assert len(runs) == 1 and runs[0]["command"] == "session"
    assert_sentinel_absent(json.dumps(runs), where="a session run row")
    assert runs[0]["summary"] == (
        f"session · interactive · {len(SENTINEL)} bytes · {len(SENTINEL)} chars"
    )


# --------------------------------------------------------------------------- #
# what is displayed
# --------------------------------------------------------------------------- #
def test_history_runs_show_and_audit_reveal_nothing(
    cli: Cli, provider: RecordingProvider, db_query: Query
) -> None:
    assert ask_sentinel(cli).exit_code == 0
    run_id = db_query("SELECT * FROM runs")[0]["id"]
    for argv in (
        ["history"],
        ["--json", "history"],
        ["runs", "show", run_id],
        ["--json", "runs", "show", run_id],
        ["audit"],
        ["--json", "audit"],
    ):
        result = cli(argv)
        assert result.exit_code == 0, result.output
        assert_sentinel_absent(result.output, where=f"`sobai {' '.join(argv)}`")


def test_history_still_reports_the_useful_metadata(
    cli: Cli, provider: RecordingProvider, db_query: Query
) -> None:
    assert ask_sentinel(cli).exit_code == 0
    runs = json.loads(cli(["--json", "history"]).stdout)["runs"]
    assert len(runs) == 1
    row = runs[0]
    assert row["command"] == "ask"
    assert row["provider"] == "ollama"
    assert row["model"] == "x"  # `ollama:x` resolves to provider + model id
    assert row["status"] == "ok"
    assert row["auth_mode"] == "local"
    assert (row["input_tokens"], row["output_tokens"]) == (12, 4)
    assert row["cost_kind"] == "actual"
    assert row["duration_ms"] is not None

    detail = json.loads(cli(["--json", "runs", "show", row["id"][:12]]).stdout)["run"]
    assert detail["id"] == row["id"]
    text = cli(["runs", "show", row["id"][:12]]).stdout
    assert "ask · argument" in text  # the summary is still shown; it is just content-free
    usage = json.loads(cli(["--json", "usage"]).stdout)["rows"]
    assert [(r["provider"], r["input_tokens"], r["runs"]) for r in usage] == [("ollama", 12, 1)]


# --------------------------------------------------------------------------- #
# databases written by older development builds
# --------------------------------------------------------------------------- #
def test_a_legacy_prompt_prefix_is_left_alone_but_rendered_safely(
    cli: Cli, sobai_env: dict[str, str], db_query: Query
) -> None:
    """History written by an older build is a user's data: shown, never rewritten.

    It can still hold a prompt prefix, so it is rendered as untrusted text —
    a stored prompt must not be able to drive the terminal when it is read back.
    """
    path = Path(sobai_env["SOBAI_DATA_DIR"]) / "state.db"
    Database(path).close()  # create the schema the way the application does
    legacy = f"{SENTINEL}\x1b[2J\x1b]0;pwned\x07"
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO runs (id, started_at, command, status, summary) VALUES (?,?,?,?,?)",
            ("0" * 32, "2026-01-01T00:00:00+00:00", "ask", "ok", legacy),
        )
    conn.close()

    result = cli(["runs", "show", "0" * 32])
    assert result.exit_code == 0, result.output
    assert "\x1b[2J" not in result.stdout
    assert "\x1b]0;" not in result.stdout
    # The row is still the user's: nothing deleted it or rewrote it behind them.
    assert db_query("SELECT * FROM runs")[0]["summary"] == legacy


# --------------------------------------------------------------------------- #
# redaction is unaffected
# --------------------------------------------------------------------------- #
def test_a_credential_shaped_prompt_leaves_no_trace(
    cli: Cli, provider: RecordingProvider, db_query: Query
) -> None:
    key = "sk-ant-livekey1234567890abcd"
    assert cli(["-p", "ollama", "-m", "ollama:x", "ask", f"is {key} valid"]).exit_code == 0
    stored = json.dumps(db_query("SELECT * FROM runs") + db_query("SELECT * FROM audit"))
    assert key not in stored
    assert "sk-ant-" not in stored


def test_a_registered_secret_in_a_summary_is_still_redacted(tmp_path: Path) -> None:
    """The storage layer keeps its own redaction pass, independent of callers."""
    from sobai.core.redaction import REDACTED, register_secret

    register_secret("hunter2-hunter2")
    db = Database(tmp_path / "state.db")
    try:
        db.start_run("r1", "ask", summary="ask · argument · hunter2-hunter2")
        assert REDACTED in str(db.get_run("r1")["summary"])
    finally:
        db.close()


def test_a_provider_error_is_redacted_and_keeps_its_exit_code(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, db_query: Query
) -> None:
    key = "sk-ant-leakedfromupstream123"
    monkeypatch.setattr(
        "sobai.cli.common.build_provider",
        lambda *a, **k: RecordingProvider(fail=ProviderError(f"upstream echoed {key}")),
    )
    result = ask_sentinel(cli)
    assert result.exit_code == int(ExitCode.PROVIDER)
    assert key not in result.output
    assert "***REDACTED***" in result.output
    assert_sentinel_absent(json.dumps(db_query("SELECT * FROM runs")), where="a failed run row")
    assert db_query("SELECT * FROM runs")[0]["status"] == "error"
