from __future__ import annotations

from datetime import UTC, datetime

from sobai.connectors.notion import retrieval

from ._notion_fakes import FakeClient, data_source, page, para, todo

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


async def test_search_pages_summaries() -> None:
    client = FakeClient(search=[page("P1", "Alpha"), page("P2", "Beta")])
    rows = await retrieval.search_pages(client, None, limit=10)
    assert {r["title"] for r in rows} == {"Alpha", "Beta"}
    assert all("url" in r and "last_edited_time" in r for r in rows)


async def test_recent_pages_boundary() -> None:
    client = FakeClient(
        search=[
            page("recent", "Recent", edited="2026-08-22T00:00:00.000Z"),
            page("old", "Old", edited="2026-07-01T00:00:00.000Z"),
        ]
    )
    rows = await retrieval.recent_pages(client, since="7d", now=NOW)
    assert [r["title"] for r in rows] == ["Recent"]


async def test_read_page_normalizes_id_and_returns_provenance() -> None:
    dashed = "abcdef01-2345-6789-abcd-ef0123456789"
    client = FakeClient(
        pages={dashed: page(dashed, "Doc")},
        blocks={dashed: [para("b", "hello world")]},
    )
    # Pass a notion.so URL whose trailing id normalizes to the page's dashed id.
    out = await retrieval.read_page(
        client, "https://www.notion.so/Doc-abcdef0123456789abcdef0123456789"
    )
    assert out["title"] == "Doc"
    assert out["text"] == "hello world"
    assert out["source"]["id"] == dashed
    assert out["source"]["url"]


async def test_project_candidates_heuristic() -> None:
    client = FakeClient(
        search=[
            data_source("db1", "Projects Tracker"),
            page("p1", "Q3 Project Plan"),
            page("p2", "Grocery List"),
        ]
    )
    rows, notes = await retrieval.project_candidates(client, limit=10)
    titles = {r["title"] for r in rows}
    assert "Projects Tracker" in titles and "Q3 Project Plan" in titles
    assert "Grocery List" not in titles
    assert any("heuristic" in n.lower() for n in notes)


async def test_weekly_review_buckets_and_signals() -> None:
    created_page = page(
        "c1", "New Spec", created="2026-08-22T00:00:00.000Z", edited="2026-08-22T12:00:00.000Z"
    )
    edited_page = page(
        "e1", "Old Doc", created="2026-01-01T00:00:00.000Z", edited="2026-08-21T00:00:00.000Z"
    )
    client = FakeClient(
        search=[created_page, edited_page],
        blocks={
            "c1": [todo("t1", "ship release", checked=True), para("d1", "Decision: use SQLite")],
            "e1": [todo("t2", "write tests", checked=False), para("b1", "blocked on review")],
        },
    )
    data = await retrieval.weekly_review_data(client, since="7d", now=NOW)
    assert [p["title"] for p in data["created"]] == ["New Spec"]
    assert [p["title"] for p in data["edited"]] == ["Old Doc"]
    assert any("ship release" in t["text"] for t in data["completed_tasks"])
    assert any("write tests" in t["text"] for t in data["open_tasks"])
    assert any("Decision" in d["text"] for d in data["decisions"])
    assert any("blocked" in b["text"].lower() for b in data["possible_blockers"])
    # every observed item carries a source reference
    assert all("source" in t for t in data["completed_tasks"])
    assert data["sources"]
