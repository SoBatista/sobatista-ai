"""Block traversal and property extraction (bounded, cycle-safe).

Recursively reads a page's supported block content with explicit depth and total
bounds, prevents cycles/duplicates via a visited set, records (never fabricates)
unsupported or unavailable content, and extracts plain text from rich-text
arrays. Child pages/databases are recorded as references but not traversed
(they are separate shared objects).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import NotionClient

# Block types whose ``<type>`` object carries a ``rich_text`` array we render.
_TEXT_BLOCKS = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "quote",
    "callout",
    "toggle",
    "code",
    "to_do",
}


@dataclass(slots=True)
class TraversalLimits:
    max_depth: int = 4
    max_blocks: int = 400


@dataclass(slots=True)
class PageContent:
    title: str
    lines: list[str] = field(default_factory=list)
    child_refs: list[str] = field(default_factory=list)
    unsupported: int = 0
    blocks_read: int = 0
    truncated: bool = False


def rich_text_to_plain(rich_text: Any) -> str:
    if not isinstance(rich_text, list):
        return ""
    return "".join(str(item.get("plain_text", "")) for item in rich_text)


def _block_text(block: dict[str, Any]) -> str | None:
    btype = block.get("type", "")
    if btype not in _TEXT_BLOCKS:
        return None
    payload = block.get(btype, {}) or {}
    text = rich_text_to_plain(payload.get("rich_text"))
    if btype == "to_do":
        mark = "[x]" if payload.get("checked") else "[ ]"
        return f"{mark} {text}".rstrip()
    return text or None


def page_title(page: dict[str, Any]) -> str:
    """Extract a page/data_source title without fabricating one."""
    props = page.get("properties", {})
    if isinstance(props, dict):
        for prop in props.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title = rich_text_to_plain(prop.get("title"))
                if title:
                    return title
    # Data sources / databases expose a top-level ``title`` rich-text array.
    top = rich_text_to_plain(page.get("title"))
    return top or "Untitled"


def page_provenance(page: dict[str, Any]) -> dict[str, Any]:
    """Stable source reference + timestamps for a page/data_source."""
    return {
        "id": page.get("id"),
        "object": page.get("object"),
        "url": page.get("url"),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "archived": bool(page.get("archived") or page.get("in_trash")),
        "parent": page.get("parent"),
    }


async def read_page_content(
    client: NotionClient, page: dict[str, Any], limits: TraversalLimits | None = None
) -> PageContent:
    """Recursively read a page's supported block text within bounds."""
    limits = limits or TraversalLimits()
    content = PageContent(title=page_title(page))
    visited: set[str] = set()
    await _walk(client, str(page["id"]), depth=0, limits=limits, content=content, visited=visited)
    return content


async def _walk(
    client: NotionClient,
    block_id: str,
    *,
    depth: int,
    limits: TraversalLimits,
    content: PageContent,
    visited: set[str],
) -> None:
    if block_id in visited:  # cycle / duplicate guard
        return
    visited.add(block_id)
    if depth > limits.max_depth or content.blocks_read >= limits.max_blocks:
        content.truncated = True
        return

    try:
        # Fetch a normal page of children (the client caps per request); the
        # overall bound is enforced by the ``max_blocks`` check in the loop so
        # truncation is detected rather than silently hidden by the fetch cap.
        children = await client.block_children(block_id)
    except Exception:  # a single unreadable subtree must not abort the whole page
        content.truncated = True
        return

    for block in children:
        if content.blocks_read >= limits.max_blocks:
            content.truncated = True
            return
        content.blocks_read += 1
        btype = block.get("type", "")

        if btype in ("child_page", "child_database"):
            ref = (block.get(btype, {}) or {}).get("title") or "(untitled)"
            content.child_refs.append(f"{btype}: {ref}")
            continue
        if btype == "unsupported":
            content.unsupported += 1
            continue
        # A synced_block mirror (synced_from set) duplicates another block's
        # children; only the original (synced_from null) owns them.
        if (
            btype == "synced_block"
            and (block.get("synced_block", {}) or {}).get("synced_from") is not None
        ):
            continue

        text = _block_text(block)
        if text:
            content.lines.append(("  " * depth) + text)

        if block.get("has_children") and btype not in ("child_page", "child_database"):
            await _walk(
                client,
                str(block["id"]),
                depth=depth + 1,
                limits=limits,
                content=content,
                visited=visited,
            )
