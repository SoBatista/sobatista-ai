"""Notion report structures with mandatory source provenance.

Every report keeps three things separate and explicit:

* **observed** — facts retrieved from the Notion API, verbatim;
* **sources** — stable page/data_source references (id, url, timestamps) for the
  observed facts;
* **ai_interpretation** — present only when a model was invoked, always clearly
  labeled and never mixed into the observed facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TIMEZONE_NOTE = "UTC (Notion stores timestamps in UTC)"
API_NOTE = "notion.v1"


@dataclass(slots=True)
class Report:
    report: str
    observed: Any
    sources: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    ai_interpretation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.report,
            "meta": {
                "api": API_NOTE,
                "timezone": TIMEZONE_NOTE,
                "params": self.params,
            },
            "observed": self.observed,
            "sources": self.sources,
            "notes": self.notes,
            "ai_interpretation": self.ai_interpretation,
        }
