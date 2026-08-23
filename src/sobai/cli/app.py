"""The ``sobai`` Typer application: global options, command wiring, entry point."""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from sobai import __version__
from sobai.core.context import AppContext, GlobalOptions
from sobai.core.errors import ExitCode, SobaiError
from sobai.core.redaction import redact

# Typer vendors click as ``typer._click`` (Typer >= 0.13); fall back to an external
# click install for older layouts. We need ClickException to render usage errors.
try:
    from typer._click.exceptions import ClickException as _ClickException
except Exception:  # pragma: no cover - depends on Typer packaging
    from click.exceptions import (  # type: ignore[import-not-found,no-redef]
        ClickException as _ClickException,
    )

from .aliases import aliases_app
from .ask import ask_command
from .common import get_ctx
from .config_cmd import config_show, connections, privacy_explain
from .doctor import doctor
from .history_cmd import audit, history, runs_app
from .init import init
from .profiles_cmd import profile_app
from .providers_cmd import (
    connect_command,
    disconnect_command,
    model_app,
    models_app,
    provider_app,
    providers_app,
)
from .update_cmd import update_command
from .usage_cmd import usage_command
from .youtube_cmd import youtube_app

app = typer.Typer(
    name="sobai",
    help="SoBatista AI — One CLI. Any model. Your tools.",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Track the active context so the top-level error handler can render with the
# right mode (json/quiet/no-color) and so resources are closed on exit.
_ACTIVE_CTX: AppContext | None = None


def _version_callback(value: bool) -> None:
    if value:
        print(f"sobai {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    provider: Annotated[
        str | None, typer.Option("--provider", "-p", help="Provider or alias for this run.")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="Model alias or provider:model id.")
    ] = None,
    profile: Annotated[
        str | None, typer.Option("--profile", help="Configuration profile to use.")
    ] = None,
    local_only: Annotated[
        bool, typer.Option("--local-only", help="Hard-fail if any data would leave the machine.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; do not execute tool calls.")
    ] = False,
    apply: Annotated[
        bool, typer.Option("--apply", help="Enable write actions (Phase 3+).")
    ] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable JSON output.")] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress non-essential output.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable colored output.")] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
        ),
    ] = False,
) -> None:
    """Global options apply to every command."""
    global _ACTIVE_CTX
    opts = GlobalOptions(
        provider=provider,
        model=model,
        profile=profile,
        local_only=local_only,
        dry_run=dry_run,
        apply=apply,
        json=json_out,
        quiet=quiet,
        no_color=no_color,
    )
    _ACTIVE_CTX = AppContext.build(opts)
    ctx.obj = _ACTIVE_CTX
    # Ensure the SQLite connection is closed when the command finishes, even
    # under the test runner (which invokes the callback but not main()).
    ctx.call_on_close(_ACTIVE_CTX.close)


# -- small top-level commands defined inline -------------------------------
def tools_list(ctx: typer.Context) -> None:
    """List tools currently available to models (provided by connectors)."""
    app_ctx = get_ctx(ctx)
    if app_ctx.ui.json_mode:
        app_ctx.ui.print_json({"tools": []})
        return
    app_ctx.ui.print(
        "[muted]No tools are registered in this build. Tools are provided by "
        "connectors (YouTube, Notion) and appear here once connectors are enabled.[/muted]"
    )


def update_check(ctx: typer.Context) -> None:
    """Check whether a newer release is available (skipped under --local-only)."""
    app_ctx = get_ctx(ctx)
    current = __version__
    if app_ctx.opts.local_only:
        app_ctx.ui.info(f"Version {current}. Network check skipped (--local-only).")
        return
    latest: str | None = None
    try:
        import httpx

        resp = httpx.get("https://pypi.org/pypi/sobatista-ai/json", timeout=5.0)
        if resp.status_code == 200:
            latest = resp.json().get("info", {}).get("version")
    except Exception:
        latest = None
    if app_ctx.ui.json_mode:
        app_ctx.ui.print_json({"current": current, "latest": latest})
        return
    if latest and latest != current:
        app_ctx.ui.print(f"Update available: {current} -> {latest}")
        app_ctx.ui.print(
            "  [info]uv tool upgrade sobatista-ai[/info]  or  "
            "[info]pipx upgrade sobatista-ai[/info]"
        )
    elif latest:
        app_ctx.ui.success(f"Up to date ({current}).")
    else:
        app_ctx.ui.info(f"Version {current}. Could not reach PyPI to check for updates.")


# -- command registration --------------------------------------------------
app.command("ask")(ask_command)
app.command("init")(init)
app.command("doctor")(doctor)
app.command("connect")(connect_command)
app.command("disconnect")(disconnect_command)
app.command("connections")(connections)
app.command("history")(history)
app.command("usage")(usage_command)
app.command("audit")(audit)
app.command("update-check")(update_check)
app.command("update")(update_command)
app.command("tools")(tools_list)

app.add_typer(providers_app, name="providers")
app.add_typer(models_app, name="models")
app.add_typer(provider_app, name="provider")
app.add_typer(model_app, name="model")
app.add_typer(profile_app, name="profile")
app.add_typer(runs_app, name="runs")
app.add_typer(aliases_app, name="aliases")
app.add_typer(youtube_app, name="youtube")

config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)
config_app.command("show")(config_show)
app.add_typer(config_app, name="config")

privacy_app = typer.Typer(help="Privacy and data-handling information.", no_args_is_help=True)
privacy_app.command("explain")(privacy_explain)
app.add_typer(privacy_app, name="privacy")


def _emit_error(exc: SobaiError) -> None:
    ctx = _ACTIVE_CTX
    if ctx is not None and ctx.ui.json_mode:
        ctx.ui.print_json(
            {"error": {"type": type(exc).__name__, "message": exc.message, "hint": exc.hint}}
        )
    elif ctx is not None:
        ctx.ui.error(exc.message, hint=exc.hint)
    else:  # pragma: no cover - error before context was built
        from rich.console import Console

        err = Console(stderr=True)
        err.print(f"[bold red]error:[/bold red] {redact(exc.message)}")
        if exc.hint:
            err.print(f"  {redact(exc.hint)}")


def main() -> None:
    """Console-script entry point with typed exit codes."""
    try:
        app(standalone_mode=False)
    except SobaiError as exc:
        _emit_error(exc)
        sys.exit(int(exc.exit_code))
    except typer.Abort:
        sys.exit(int(ExitCode.CANCELLED))
    except typer.Exit as exc:
        sys.exit(int(getattr(exc, "exit_code", 0)))
    except _ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(int(ExitCode.CANCELLED))
    finally:
        if _ACTIVE_CTX is not None:
            _ACTIVE_CTX.close()


if __name__ == "__main__":  # pragma: no cover
    main()
