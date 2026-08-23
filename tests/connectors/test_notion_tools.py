from __future__ import annotations

import json

from sobai.connectors.notion.tools import build_registry

from ._notion_fakes import FakeClient, page, para


def test_registry_read_only_schemas() -> None:
    registry = build_registry(FakeClient())
    names = set(registry.names())
    assert {"notion_search", "notion_recent", "notion_read_page", "notion_projects"} == names
    for spec in registry.specs(include_writes=True):
        assert spec.writes is False
        assert spec.input_schema["type"] == "object"


async def test_search_tool_returns_provenance() -> None:
    registry = build_registry(FakeClient(search=[page("P1", "Alpha")]))
    tool = registry.get("notion_search")
    assert tool is not None
    out = json.loads(await tool.run({"query": "Alpha"}))
    assert out["source"]["api"] == "notion.v1"
    assert out["observed"][0]["title"] == "Alpha"
    assert out["observed"][0]["url"]


async def test_read_page_tool() -> None:
    dashed = "abcdef01-2345-6789-abcd-ef0123456789"
    registry = build_registry(
        FakeClient(pages={dashed: page(dashed, "Doc")}, blocks={dashed: [para("b", "body")]})
    )
    tool = registry.get("notion_read_page")
    assert tool is not None
    out = json.loads(await tool.run({"page": dashed}))
    assert out["title"] == "Doc"
    assert out["text"] == "body"
    assert out["source"]["id"] == dashed
