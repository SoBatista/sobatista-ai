"""Report structures with mandatory provenance.

Every YouTube report separates:

* **meta** — date range, timezone, comparison window, data freshness, and the
  exact query/source metadata used to produce it;
* **observed** — the facts returned by the API, verbatim;
* **ai_interpretation** — present only when a model was invoked, and always
  clearly labeled and kept separate from the observed facts.

This makes it impossible to silently blend AI inference with measured data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# YouTube Analytics reports day-level data in Pacific Time.
REPORT_TIMEZONE = "America/Los_Angeles (Pacific Time)"
FRESHNESS_NOTE = (
    "YouTube Analytics data typically finalizes after 24-72 hours; the most "
    "recent day(s) in this range may be incomplete."
)


@dataclass(slots=True)
class SourceMeta:
    """Exactly which API/query produced the observed data."""

    api: str
    endpoint: str
    ids: str | None = None
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: str | None = None
    sort: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "api": self.api,
            "endpoint": self.endpoint,
            "ids": self.ids,
            "metrics": self.metrics,
            "dimensions": self.dimensions,
            "filters": self.filters,
            "sort": self.sort,
        }


@dataclass(slots=True)
class ReportMeta:
    report: str
    date_range: dict[str, str]
    source: SourceMeta
    timezone: str = REPORT_TIMEZONE
    freshness: str = FRESHNESS_NOTE
    comparison: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.report,
            "date_range": self.date_range,
            "timezone": self.timezone,
            "freshness": self.freshness,
            "comparison": self.comparison,
            "source": self.source.to_dict(),
        }


@dataclass(slots=True)
class Report:
    meta: ReportMeta
    observed: Any
    notes: list[str] = field(default_factory=list)
    ai_interpretation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.meta.report,
            "meta": self.meta.to_dict(),
            "observed": self.observed,
            "notes": self.notes,
            "ai_interpretation": self.ai_interpretation,
        }
