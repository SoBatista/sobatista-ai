"""Run history, run detail, and the privacy audit log."""

from __future__ import annotations

from typing import Annotated

import typer

from sobai.core.errors import NotFoundError
from sobai.ui.console import render_untrusted

from .common import get_ctx

runs_app = typer.Typer(help="Inspect individual runs.", no_args_is_help=True)


def history(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many runs to show.")] = 20,
) -> None:
    """Show recent runs."""
    app = get_ctx(ctx)
    runs = app.db.list_runs(limit=limit)
    if app.ui.json_mode:
        app.ui.print_json({"runs": runs})
        return
    rows = [
        [
            r["id"][:12],
            r["started_at"][:19],
            r["command"],
            r.get("provider") or "-",
            r.get("model") or "-",
            r.get("status") or "-",
        ]
        for r in runs
    ]
    if rows:
        app.ui.table("Runs", ["id", "started", "command", "provider", "model", "status"], rows)
    else:
        app.ui.print("[muted]No runs recorded yet.[/muted]")


@runs_app.command("show")
def runs_show(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="Run id (prefix allowed).")],
) -> None:
    """Show details and tool calls for a run."""
    app = get_ctx(ctx)
    run = app.db.get_run(run_id)
    if run is None:
        # Allow prefix match for convenience.
        matches = [r for r in app.db.list_runs(limit=500) if r["id"].startswith(run_id)]
        if len(matches) == 1:
            run = matches[0]
        elif len(matches) > 1:
            raise NotFoundError(f"Ambiguous run id prefix '{run_id}'.")
    if run is None:
        raise NotFoundError(f"No run matching '{run_id}'.")
    tool_calls = app.db.tool_calls_for(run["id"])
    if app.ui.json_mode:
        app.ui.print_json({"run": run, "tool_calls": tool_calls})
        return
    app.ui.rule(f"Run {run['id'][:12]}")
    # Stored values are rendered as untrusted text. New summaries are content-free,
    # but a database written by a pre-0.2.0 development build can still hold a
    # prompt prefix, and a prompt is not something a terminal should interpret.
    for key in (
        "command",
        "provider",
        "model",
        "profile",
        "auth_mode",
        "local_only",
        "status",
        "exit_code",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "tool_rounds",
        "duration_ms",
        "cost_usd",
        "cost_kind",
        "started_at",
        "finished_at",
        "summary",
    ):
        app.ui.print(f"  [heading]{key}[/heading]: {render_untrusted(str(run.get(key)))}")
    if tool_calls:
        rows = [
            [str(t["round"]), t["tool_name"], "write" if t["writes"] else "read", t["status"]]
            for t in tool_calls
        ]
        app.ui.table("Tool calls", ["round", "tool", "kind", "status"], rows)


def audit(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many events to show.")] = 50,
) -> None:
    """Show the privacy audit log (what data class left the machine, and where)."""
    app = get_ctx(ctx)
    events = app.db.list_audit(limit=limit)
    if app.ui.json_mode:
        app.ui.print_json({"audit": events})
        return
    rows = [
        [
            e["ts"][:19],
            e["event"],
            e.get("connector") or "-",
            e.get("provider") or "-",
            e.get("data_class") or "-",
        ]
        for e in events
    ]
    if rows:
        app.ui.table("Audit log", ["time", "event", "connector", "provider", "class"], rows)
    else:
        app.ui.print("[muted]No audit events recorded yet.[/muted]")
