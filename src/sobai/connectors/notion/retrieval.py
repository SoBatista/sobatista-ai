"""Higher-level read-only Notion retrieval used by CLI commands and tools.

All functions return observed data with source provenance and never fabricate a
property or block that is unavailable. Heuristics (projects, decisions, blockers)
are transparent and clearly labeled — never presented as authoritative.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .blocks import PageContent, TraversalLimits, page_provenance, page_title, read_page_content
from .client import NotionClient
from .ids import normalize_id
from .period import cutoff, is_within, parse_notion_ts

# Transparent, documented keyword heuristics (case-insensitive substring match).
_DECISION_WORDS = ("decision", "decided", "we will", "agreed to", "conclusion:")
_BLOCKER_WORDS = ("blocked", "blocker", "waiting on", "stuck", "at risk", "blocking")
_PROJECT_WORDS = ("project", "initiative", "epic")

_WEEKLY_READ_LIMIT = 12  # pages whose body is scanned for tasks/decisions/blockers


def summarize_page(page: dict[str, Any]) -> dict[str, Any]:
    """A compact, provenance-carrying summary of a page/data_source object."""
    prov = page_provenance(page)
    return {
        "id": prov["id"],
        "object": prov["object"],
        "title": page_title(page),
        "url": prov["url"],
        "created_time": prov["created_time"],
        "last_edited_time": prov["last_edited_time"],
        "archived": prov["archived"],
    }


async def search_pages(
    client: NotionClient,
    query: str | None,
    *,
    object_type: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    results = await client.search(query, object_type=object_type, max_items=limit)
    return [summarize_page(p) for p in results]


async def recent_pages(
    client: NotionClient, *, since: str, limit: int = 50, now: datetime | None = None
) -> list[dict[str, Any]]:
    boundary = cutoff(since, now=now)
    results = await client.search(None, max_items=limit * 3)
    recent = [p for p in results if is_within(p.get("last_edited_time"), boundary)]
    return [summarize_page(p) for p in recent[:limit]]


async def read_page(
    client: NotionClient, id_or_url: str, *, limits: TraversalLimits | None = None
) -> dict[str, Any]:
    page_id = normalize_id(id_or_url)
    page = await client.retrieve_page(page_id)
    content: PageContent = await read_page_content(client, page, limits)
    prov = page_provenance(page)
    notes: list[str] = []
    if content.unsupported:
        notes.append(f"{content.unsupported} unsupported block(s) skipped.")
    if content.truncated:
        notes.append("Content truncated at the configured traversal limits.")
    return {
        "source": prov,
        "title": content.title,
        "text": "\n".join(content.lines),
        "child_refs": content.child_refs,
        "blocks_read": content.blocks_read,
        "notes": notes,
    }


async def project_candidates(
    client: NotionClient, *, limit: int = 25
) -> tuple[list[dict[str, Any]], list[str]]:
    """Heuristic project candidates. Returns (candidates, notes)."""
    notes = [
        "Heuristic: pages/data_sources whose title contains 'project'/'initiative'/"
        "'epic'. Not authoritative — no dedicated project database was assumed."
    ]
    data_sources = await client.search(None, object_type="data_source", max_items=limit)
    pages = await client.search(None, object_type="page", max_items=limit * 2)
    out: list[dict[str, Any]] = []
    for obj in [*data_sources, *pages]:
        title = page_title(obj).lower()
        if any(word in title for word in _PROJECT_WORDS):
            out.append(summarize_page(obj))
        if len(out) >= limit:
            break
    return out, notes


def _scan(lines: list[str], words: tuple[str, ...]) -> list[str]:
    lowered = [(line, line.lower()) for line in lines]
    return [line.strip() for line, low in lowered if any(w in low for w in words) and line.strip()]


async def weekly_review_data(
    client: NotionClient,
    *,
    since: str = "7d",
    now: datetime | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Gather observed weekly-review facts with source references (no inference)."""
    boundary = cutoff(since, now=now)
    results = await client.search(None, max_items=limit * 3)
    recent = [p for p in results if is_within(p.get("last_edited_time"), boundary)][:limit]

    created: list[dict[str, Any]] = []
    edited: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for page in recent:
        summary = summarize_page(page)
        sources.append({"id": summary["id"], "title": summary["title"], "url": summary["url"]})
        created_dt = parse_notion_ts(page.get("created_time"))
        if created_dt is not None and created_dt >= boundary:
            created.append(summary)
        else:
            edited.append(summary)

    completed: list[dict[str, Any]] = []
    open_tasks: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    scanned = 0
    scan_notes: list[str] = []
    for page in recent[:_WEEKLY_READ_LIMIT]:
        try:
            content = await read_page_content(
                client, page, TraversalLimits(max_depth=3, max_blocks=80)
            )
        except Exception:  # one unreadable page must not fail the whole review
            scan_notes.append(f"Could not read page {page.get('id')}.")
            continue
        scanned += 1
        ref = {"id": page.get("id"), "title": content.title, "url": page.get("url")}
        for line in content.lines:
            stripped = line.strip()
            if stripped.startswith("[x]"):
                completed.append({"text": stripped, "source": ref})
            elif stripped.startswith("[ ]"):
                open_tasks.append({"text": stripped, "source": ref})
        for line in _scan(content.lines, _DECISION_WORDS):
            decisions.append({"text": line, "source": ref})
        for line in _scan(content.lines, _BLOCKER_WORDS):
            blockers.append({"text": line, "source": ref})

    projects, project_notes = await project_candidates(client, limit=25)

    notes = [
        f"Window: last '{since}' (UTC), boundary {boundary.isoformat()}.",
        f"Scanned {scanned} of {len(recent)} recently-edited page(s) for tasks/decisions/blockers "
        f"(limit {_WEEKLY_READ_LIMIT}).",
        "Tasks come from to-do blocks; decisions/blockers use documented keyword heuristics "
        "and may miss or over-match.",
        *project_notes,
        *scan_notes,
    ]
    return {
        "window": {"since": since, "boundary": boundary.isoformat(), "timezone": "UTC"},
        "created": created,
        "edited": edited,
        "completed_tasks": completed,
        "open_tasks": open_tasks,
        "decisions": decisions,
        "possible_blockers": blockers,
        "projects_mentioned": projects,
        "sources": sources,
        "notes": notes,
    }
