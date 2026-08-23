from __future__ import annotations

import pytest

from sobai.connectors.notion.ids import normalize_id
from sobai.core.errors import ConnectorError

ID = "abcdef0123456789abcdef0123456789"
DASHED = "abcdef01-2345-6789-abcd-ef0123456789"


def test_bare_hex_id() -> None:
    assert normalize_id(ID) == DASHED


def test_already_dashed() -> None:
    assert normalize_id(DASHED) == DASHED
    assert normalize_id(DASHED.upper()) == DASHED


def test_url_with_title_slug() -> None:
    # A title slug ending in hex letters must not merge with the id.
    assert normalize_id(f"https://www.notion.so/My-Page-{ID}") == DASHED


def test_url_with_query_and_workspace() -> None:
    url = f"https://www.notion.so/Team/Weekly-Review-{ID}?pvs=4"
    assert normalize_id(url) == DASHED


def test_url_bare_host() -> None:
    assert normalize_id(f"notion.so/{ID}") == DASHED


def test_rejects_non_notion_host() -> None:
    with pytest.raises(ConnectorError, match="non-Notion"):
        normalize_id(f"https://evil.example.com/{ID}")


def test_rejects_url_without_id() -> None:
    with pytest.raises(ConnectorError):
        normalize_id("https://www.notion.so/just-a-title")


def test_rejects_junk() -> None:
    for bad in ("", "not a url", "1234"):
        with pytest.raises(ConnectorError):
            normalize_id(bad)
