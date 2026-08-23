from __future__ import annotations

from datetime import date

import pytest

from sobai.connectors.youtube.period import parse_period, previous_range, resolve_range
from sobai.core.errors import ConnectorError

TODAY = date(2026, 8, 23)


def test_parse_period_units() -> None:
    assert parse_period("30d") == 30
    assert parse_period("12w") == 84
    assert parse_period("3m") == 90
    assert parse_period("1y") == 365
    assert parse_period("7") == 7  # bare int == days


def test_parse_period_invalid() -> None:
    for bad in ("abc", "0d", "-5", "", "3x"):
        with pytest.raises(ConnectorError):
            parse_period(bad)


def test_resolve_relative_includes_today() -> None:
    r = resolve_range(period="30d", today=TODAY)
    assert r.end == TODAY
    assert r.start == date(2026, 7, 25)  # 30-day inclusive window
    assert r.days == 30


def test_resolve_explicit_range() -> None:
    r = resolve_range(start="2026-01-01", end="2026-01-31", today=TODAY)
    assert r.start == date(2026, 1, 1)
    assert r.end == date(2026, 1, 31)
    assert r.days == 31


def test_resolve_requires_both_explicit() -> None:
    with pytest.raises(ConnectorError):
        resolve_range(start="2026-01-01", today=TODAY)


def test_resolve_rejects_reversed_and_future() -> None:
    with pytest.raises(ConnectorError):
        resolve_range(start="2026-02-01", end="2026-01-01", today=TODAY)
    with pytest.raises(ConnectorError):
        resolve_range(start="2026-01-01", end="2027-01-01", today=TODAY)


def test_resolve_bad_date_format() -> None:
    with pytest.raises(ConnectorError):
        resolve_range(start="01/01/2026", end="2026-01-31", today=TODAY)


def test_previous_range_is_adjacent_and_equal_length() -> None:
    cur = resolve_range(period="30d", today=TODAY)
    prev = previous_range(cur)
    assert prev.end == date(2026, 7, 24)  # day before current start
    assert prev.days == cur.days
    assert prev.start == date(2026, 6, 25)
