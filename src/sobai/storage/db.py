"""SQLite-backed local state.

Holds four kinds of local state, all owner-only on disk:

* **runs** — one row per model-backed invocation (for ``sobai history`` / ``runs show``)
* **audit** — privacy-preserving records of what data class left the machine, to
  which provider, via which connector (never the content itself)
* **tool_calls** — per-round tool execution records for a run
* **cache** — metadata for cached connector payloads (payload files live in the cache dir)
* **kb_items** — imported knowledge-base entries with provenance and dedup hashes

The database is intentionally synchronous: SQLite is fast for a single-user CLI
and avoids an async driver dependency. All writes go through short-lived
transactions.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sobai.core.classification import DataClass
from sobai.core.redaction import redact

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    command       TEXT NOT NULL,
    provider      TEXT,
    model         TEXT,
    profile       TEXT,
    local_only    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running',
    exit_code     INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    summary       TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    round       INTEGER NOT NULL,
    tool_name   TEXT NOT NULL,
    writes      INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL,
    duration_ms INTEGER,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    run_id      TEXT,
    event       TEXT NOT NULL,
    connector   TEXT,
    provider    TEXT,
    data_class  TEXT,
    detail      TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    connector   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    data_class  TEXT,
    path        TEXT,
    size_bytes  INTEGER,
    etag        TEXT
);

CREATE TABLE IF NOT EXISTS kb_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_hash TEXT NOT NULL UNIQUE,
    kind        TEXT,
    title       TEXT,
    frontmatter TEXT,
    excerpt     TEXT,
    imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Thin repository over the SoBatista AI SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with contextlib.suppress(OSError):  # pragma: no cover
            self.path.chmod(0o600)
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    # -- lifecycle ---------------------------------------------------------
    def _migrate(self) -> None:
        with self._tx() as cur:
            cur.executescript(_SCHEMA)
            row = cur.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                cur.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    # -- runs --------------------------------------------------------------
    def start_run(
        self,
        run_id: str,
        command: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        profile: str | None = None,
        local_only: bool = False,
        summary: str | None = None,
    ) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO runs (id, started_at, command, provider, model, profile, "
                "local_only, status, summary) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    _now(),
                    command,
                    provider,
                    model,
                    profile,
                    int(local_only),
                    "running",
                    redact(summary) if summary else None,
                ),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        exit_code: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE runs SET finished_at=?, status=?, exit_code=?, input_tokens=?, "
                "output_tokens=?, cost_usd=? WHERE id=?",
                (_now(), status, exit_code, input_tokens, output_tokens, cost_usd, run_id),
            )

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    # -- tool calls --------------------------------------------------------
    def record_tool_call(
        self,
        run_id: str,
        *,
        round_: int,
        tool_name: str,
        writes: bool,
        status: str,
        duration_ms: int | None = None,
    ) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO tool_calls (run_id, round, tool_name, writes, status, "
                "duration_ms, created_at) VALUES (?,?,?,?,?,?,?)",
                (run_id, round_, tool_name, int(writes), status, duration_ms, _now()),
            )

    def tool_calls_for(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM tool_calls WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- audit -------------------------------------------------------------
    def record_audit(
        self,
        event: str,
        *,
        run_id: str | None = None,
        connector: str | None = None,
        provider: str | None = None,
        data_class: DataClass | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Record a privacy-preserving audit event.

        ``detail`` is JSON-encoded and redacted; it must never contain raw
        connector content — only metadata (counts, ranges, categories).
        """
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO audit (ts, run_id, event, connector, provider, data_class, detail) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    _now(),
                    run_id,
                    event,
                    connector,
                    provider,
                    data_class.value if data_class else None,
                    redact(json.dumps(detail)) if detail else None,
                ),
            )

    def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- kb import ---------------------------------------------------------
    def upsert_kb_item(
        self,
        *,
        source: str,
        source_path: str,
        source_hash: str,
        kind: str | None,
        title: str | None,
        frontmatter: dict[str, Any] | None,
        excerpt: str | None,
    ) -> bool:
        """Insert a KB item; returns True if newly inserted, False if duplicate."""
        with self._tx() as cur:
            existing = cur.execute(
                "SELECT 1 FROM kb_items WHERE source_hash=?", (source_hash,)
            ).fetchone()
            if existing:
                return False
            cur.execute(
                "INSERT INTO kb_items (source, source_path, source_hash, kind, title, "
                "frontmatter, excerpt, imported_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    source,
                    source_path,
                    source_hash,
                    kind,
                    title,
                    json.dumps(frontmatter) if frontmatter else None,
                    excerpt,
                    _now(),
                ),
            )
            return True

    def count_kb_items(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM kb_items").fetchone()
        return int(row["n"])
