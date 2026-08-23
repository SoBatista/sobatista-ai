from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sobai.connectors.notion.period import cutoff, is_within, parse_notion_ts, parse_since
from sobai.core.errors import ConnectorError

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def test_parse_since_units() -> None:
    assert parse_since("7d") == timedelta(days=7)
    assert parse_since("24h") == timedelta(hours=24)
    assert parse_since("4w") == timedelta(weeks=4)
    assert parse_since("3m") == timedelta(days=90)
    assert parse_since("5") == timedelta(days=5)


def test_parse_since_invalid() -> None:
    for bad in ("0d", "-1", "abc", "", "3x"):
        with pytest.raises(ConnectorError):
            parse_since(bad)


def test_cutoff_is_timezone_aware() -> None:
    c = cutoff("7d", now=NOW)
    assert c.tzinfo is not None
    assert c == NOW - timedelta(days=7)


def test_parse_notion_ts_handles_z_and_naive() -> None:
    dt = parse_notion_ts("2026-08-20T10:00:00.000Z")
    assert dt is not None and dt.tzinfo is not None
    assert parse_notion_ts(None) is None
    assert parse_notion_ts("not-a-date") is None


def test_is_within_boundaries() -> None:
    boundary = cutoff("7d", now=NOW)  # 2026-08-16 12:00 UTC
    assert is_within("2026-08-20T00:00:00.000Z", boundary) is True
    assert is_within("2026-08-10T00:00:00.000Z", boundary) is False
    assert is_within(None, boundary) is False
