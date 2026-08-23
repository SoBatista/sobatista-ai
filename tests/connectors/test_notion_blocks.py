from __future__ import annotations

from sobai.connectors.notion.blocks import (
    TraversalLimits,
    page_provenance,
    page_title,
    read_page_content,
    rich_text_to_plain,
)

from ._notion_fakes import FakeClient, child_page, page, para, synced_mirror, todo, unsupported


def test_rich_text_to_plain() -> None:
    assert rich_text_to_plain([{"plain_text": "a"}, {"plain_text": "b"}]) == "ab"
    assert rich_text_to_plain(None) == ""


def test_page_title_and_provenance() -> None:
    p = page("P1", "My Title")
    assert page_title(p) == "My Title"
    prov = page_provenance(p)
    assert prov["id"] == "P1" and prov["url"].endswith("P1")
    assert page_title({"properties": {}}) == "Untitled"


async def test_nested_traversal_and_todo() -> None:
    client = FakeClient(
        blocks={
            "P": [para("b1", "top", children=True), todo("t1", "done it", checked=True)],
            "b1": [para("b2", "nested"), todo("t2", "todo it", checked=False)],
        }
    )
    content = await read_page_content(client, page("P"))
    joined = "\n".join(content.lines)
    assert "top" in joined
    assert "  nested" in joined  # indented one level deeper
    assert "[x] done it" in joined  # checked to-do
    assert "[ ] todo it" in joined  # unchecked to-do


async def test_depth_limit_truncates() -> None:
    client = FakeClient(
        blocks={
            "P": [para("b1", "x", children=True)],
            "b1": [para("b2", "y", children=True)],
            "b2": [para("b3", "z")],
        }
    )
    content = await read_page_content(
        client, page("P"), TraversalLimits(max_depth=1, max_blocks=99)
    )
    assert content.truncated is True
    assert "z" not in "\n".join(content.lines)


async def test_max_blocks_truncates() -> None:
    client = FakeClient(blocks={"P": [para(f"b{i}", f"line{i}") for i in range(10)]})
    content = await read_page_content(client, page("P"), TraversalLimits(max_blocks=3))
    assert content.blocks_read == 3
    assert content.truncated is True


async def test_cycle_prevention() -> None:
    # b1's child points back to the page root; must not loop forever.
    client = FakeClient(
        blocks={"P": [para("b1", "x", children=True)], "b1": [para("P", "y", children=True)]}
    )
    content = await read_page_content(client, page("P"))
    assert content.blocks_read == 2  # x, y — then the cycle is cut


async def test_unsupported_and_child_page() -> None:
    client = FakeClient(
        blocks={"P": [unsupported("u1"), child_page("c1", "Sub Page"), para("p1", "keep")]}
    )
    content = await read_page_content(client, page("P"))
    assert content.unsupported == 1
    assert any("Sub Page" in ref for ref in content.child_refs)
    assert "keep" in content.lines


async def test_synced_block_mirror_skipped() -> None:
    client = FakeClient(blocks={"P": [synced_mirror("s1")], "s1": [para("x", "should not appear")]})
    content = await read_page_content(client, page("P"))
    assert "should not appear" not in "\n".join(content.lines)


async def test_unreadable_subtree_does_not_abort() -> None:
    class Boom(FakeClient):
        async def block_children(self, bid, *, max_items=200):  # type: ignore[no-untyped-def]
            raise RuntimeError("kaboom")

    content = await read_page_content(Boom(), page("P"))
    assert content.truncated is True  # handled gracefully, no crash
