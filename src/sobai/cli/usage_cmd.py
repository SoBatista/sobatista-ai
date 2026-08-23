"""``sobai usage`` — local, privacy-preserving usage visibility.

Aggregates the local run history. Token counts and any cost figures are recorded
per run; monetary figures are always labeled by how they were obtained:

* ``claude-cli`` — subscription; a returned ``total_cost_usd`` is an
  **API-equivalent client estimate**, not an amount billed to the subscription.
* ``codex-cli`` — subscription; token usage is recorded, no monetary cost.
* direct APIs — metered; any calculated cost is an estimate.
* ``ollama`` — local; API cost ``$0`` (excludes hardware/electricity).

Provider billing dashboards remain authoritative.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from sobai.core.errors import ConfigError
from sobai.providers.registry import canonical_provider

from .common import get_ctx

_PERIOD_RE = re.compile(r"^(\d+)\s*([dwm]?)$", re.IGNORECASE)
_UNIT_DAYS = {"d": 1, "w": 7, "m": 30, "": 1}

_NOTES = [
    "claude-cli: 'subscription'; any cost is an API-equivalent client estimate, "
    "not billed to the subscription.",
    "codex-cli: 'subscription'; token usage recorded, no monetary cost.",
    "metered-api: costs (when shown) are estimates.",
    "ollama: 'local'; API cost $0 (excludes hardware/electricity).",
    "Provider billing dashboards remain authoritative.",
]


def _since(period: str | None) -> str | None:
    if not period:
        return None
    match = _PERIOD_RE.match(period.strip())
    if not match:
        raise ConfigError(f"Invalid --period '{period}'.", hint="Use forms like 7d, 4w, 3m.")
    days = int(match.group(1)) * _UNIT_DAYS[match.group(2).lower()]
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def usage_command(
    ctx: typer.Context,
    period: Annotated[
        str | None, typer.Option("--period", help="Only count runs since, e.g. 30d, 4w.")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", "-p", help="Filter by provider.")
    ] = None,
) -> None:
    """Show recorded token usage and cost estimates per provider."""
    app = get_ctx(ctx)
    since = _since(period)
    prov = canonical_provider(provider) if provider else None
    rows = app.db.usage_summary(since=since, provider=prov)

    if app.ui.json_mode:
        app.ui.print_json({"period": period, "provider": prov, "rows": rows, "notes": _NOTES})
        return

    if not rows:
        app.ui.print("[muted]No usage recorded yet.[/muted]")
        return

    table_rows = []
    for r in rows:
        cost = r.get("cost_usd")
        cost_cell = f"${cost:.4f} (est)" if cost is not None else "—"
        dur_s = (r.get("duration_ms") or 0) / 1000
        table_rows.append(
            [
                r.get("provider") or "-",
                r.get("auth_mode") or "-",
                str(r.get("runs", 0)),
                str(r.get("input_tokens", 0)),
                str(r.get("cached_input_tokens", 0)),
                str(r.get("output_tokens", 0)),
                str(r.get("reasoning_tokens", 0)),
                str(r.get("tool_rounds", 0)),
                f"{dur_s:.1f}s",
                cost_cell,
            ]
        )
    app.ui.table(
        f"Usage{f' since {period}' if period else ''}",
        [
            "provider",
            "billing",
            "runs",
            "input",
            "cached-in",
            "output",
            "reasoning",
            "tool-rounds",
            "duration",
            "cost",
        ],
        table_rows,
    )
    for note in _NOTES:
        app.ui.print(f"[muted]• {note}[/muted]")
