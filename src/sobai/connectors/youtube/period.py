"""Pure date-range helpers for analytics queries (fully unit-testable).

``today`` is injectable so date-boundary behavior can be tested deterministically
without depending on the wall clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from sobai.core.errors import ConnectorError

_PERIOD_RE = re.compile(r"^(\d+)\s*([dwmy]?)$", re.IGNORECASE)
_UNIT_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365, "": 1}


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_iso(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def parse_period(period: str) -> int:
    """Parse a period like ``30d``, ``12w``, ``3m`` (or a bare int) into days."""
    match = _PERIOD_RE.match(period.strip())
    if not match:
        raise ConnectorError(
            f"Invalid period '{period}'.",
            hint="Use forms like 30d, 12w, 3m, or an explicit --start/--end.",
        )
    value = int(match.group(1))
    if value <= 0:
        raise ConnectorError("Period must be a positive number of units.")
    return value * _UNIT_DAYS[match.group(2).lower()]


def resolve_range(
    *,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    today: date | None = None,
) -> DateRange:
    """Resolve an explicit ``--start/--end`` or a relative ``period`` to a range.

    A relative period ending "today" includes today; note that the most recent
    days may be incomplete (see reports' freshness note).
    """
    ref = today or date.today()
    if start or end:
        if not (start and end):
            raise ConnectorError(
                "Provide both --start and --end (YYYY-MM-DD), or use --period.",
            )
        try:
            s = date.fromisoformat(start)
            e = date.fromisoformat(end)
        except ValueError as exc:
            raise ConnectorError(f"Invalid date: {exc}. Use YYYY-MM-DD.") from exc
        if s > e:
            raise ConnectorError("--start must not be after --end.")
        if e > ref:
            raise ConnectorError("--end is in the future; no data exists yet.")
        return DateRange(start=s, end=e)
    days = parse_period(period or "30d")
    end_d = ref
    start_d = end_d - timedelta(days=days - 1)
    return DateRange(start=start_d, end=end_d)


def previous_range(current: DateRange) -> DateRange:
    """The equal-length window immediately preceding ``current``."""
    length = current.days
    prev_end = current.start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return DateRange(start=prev_start, end=prev_end)
