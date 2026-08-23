from __future__ import annotations

from sobai.core.classification import DataClass
from sobai.storage import Database


def test_run_lifecycle(isolated_paths) -> None:
    db = Database(isolated_paths.state_db)
    db.start_run("run1", "ask", provider="ollama", model="qwen7b", summary="hi there")
    db.finish_run("run1", status="ok", exit_code=0, input_tokens=10, output_tokens=5)
    run = db.get_run("run1")
    assert run is not None
    assert run["status"] == "ok"
    assert run["input_tokens"] == 10
    assert db.list_runs()[0]["id"] == "run1"
    db.close()


def test_summary_is_redacted(isolated_paths) -> None:
    from sobai.core.redaction import register_secret

    register_secret("hidden-token-xyz")
    db = Database(isolated_paths.state_db)
    db.start_run("r", "ask", summary="calling with hidden-token-xyz")
    run = db.get_run("r")
    assert run is not None
    assert "hidden-token-xyz" not in (run["summary"] or "")
    db.close()


def test_tool_calls_and_audit(isolated_paths) -> None:
    db = Database(isolated_paths.state_db)
    db.start_run("r", "youtube ask")
    db.record_tool_call("r", round_=1, tool_name="yt_analytics", writes=False, status="ok")
    db.record_audit(
        "egress",
        run_id="r",
        connector="youtube",
        provider="anthropic",
        data_class=DataClass.INTERNAL,
        detail={"rows": 30},
    )
    assert len(db.tool_calls_for("r")) == 1
    audit = db.list_audit()
    assert audit[0]["connector"] == "youtube"
    assert audit[0]["data_class"] == "internal"
    db.close()


def test_kb_dedup(isolated_paths) -> None:
    db = Database(isolated_paths.state_db)
    kwargs = {
        "source": "youtube-kb",
        "source_path": "/x/a.md",
        "source_hash": "hash1",
        "kind": "short",
        "title": "A",
        "frontmatter": {"format": "short"},
        "excerpt": "body",
    }
    assert db.upsert_kb_item(**kwargs) is True
    assert db.upsert_kb_item(**kwargs) is False  # duplicate hash
    assert db.count_kb_items() == 1
    db.close()


def test_db_file_permissions(isolated_paths) -> None:
    db = Database(isolated_paths.state_db)
    mode = isolated_paths.state_db.stat().st_mode & 0o777
    assert mode == 0o600
    db.close()
