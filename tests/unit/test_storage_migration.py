"""Storage schema migration (v1 -> v2) must preserve existing data."""

from __future__ import annotations

import sqlite3

from sobai.storage import Database

_V1_SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE runs (
    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, command TEXT NOT NULL,
    provider TEXT, model TEXT, profile TEXT, local_only INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running', exit_code INTEGER, input_tokens INTEGER,
    output_tokens INTEGER, cost_usd REAL, summary TEXT
);
"""


def test_v1_to_v2_adds_columns_and_preserves_rows(isolated_paths) -> None:
    path = isolated_paths.state_db
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_SCHEMA)
    conn.execute(
        "INSERT INTO runs (id, started_at, command, provider) VALUES (?,?,?,?)",
        ("old-run", "2026-01-01T00:00:00+00:00", "ask", "ollama"),
    )
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.commit()
    conn.close()

    db = Database(path)  # opening triggers migration
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(runs)")}
    assert {"auth_mode", "cached_input_tokens", "reasoning_tokens", "cost_kind"} <= cols

    old = db.get_run("old-run")
    assert old is not None and old["command"] == "ask"  # preserved

    # New-schema writes work against the migrated table.
    db.finish_run("old-run", status="ok", exit_code=0, cached_input_tokens=5, cost_kind="estimated")
    updated = db.get_run("old-run")
    assert updated["cost_kind"] == "estimated"
    assert updated["cached_input_tokens"] == 5
    db.close()


def test_fresh_db_is_v2(isolated_paths) -> None:
    db = Database(isolated_paths.state_db)
    version = db._conn.execute("SELECT version FROM schema_version").fetchone()["version"]
    assert version == 2
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(runs)")}
    assert "auth_mode" in cols
    db.close()
