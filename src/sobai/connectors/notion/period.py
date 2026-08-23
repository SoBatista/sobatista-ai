"""Timezone-aware ``--since`` boundary for recent-content filtering (pure).

Notion timestamps are UTC ISO-8601. We compute an explicit UTC cutoff and expose
a comparison helper so date boundaries are deterministic and testable (``now`` is
injectable).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sobai.core.errors import ConnectorError

_SINCE_RE = re.compile(r"^(\d+)\s*([dwmh]?)$", re.IGNORECASE)
_UNIT = {
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
    "m": timedelta(days=30),
    "": timedelta(days=1),
}


def parse_since(since: str) -> timedelta:
    """Parse ``7d`` / ``12h`` / ``4w`` / ``3m`` (or a bare int = days)."""
    match = _SINCE_RE.match(since.strip())
    if not match:
        raise ConnectorError(f"Invalid --since '{since}'.", hint="Use forms like 7d, 24h, 4w, 3m.")
    value = int(match.group(1))
    if value <= 0:
        raise ConnectorError("--since must be a positive amount.")
    return value * _UNIT[match.group(2).lower()]


def cutoff(since: str, *, now: datetime | None = None) -> datetime:
    """Return the UTC datetime marking the start of the ``since`` window."""
    ref = now or datetime.now(UTC)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    return ref - parse_since(since)


def parse_notion_ts(value: str | None) -> datetime | None:
    """Parse a Notion ISO-8601 timestamp (``...Z``) into an aware UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def is_within(value: str | None, boundary: datetime) -> bool:
    """True if a Notion timestamp is at or after the boundary."""
    ts = parse_notion_ts(value)
    return ts is not None and ts >= boundary
