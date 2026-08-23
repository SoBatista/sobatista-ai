"""Profile management: named bundles of provider/model/policy settings."""

from __future__ import annotations

from typing import Annotated

import typer

from sobai.core.config import ProfileConfig
from sobai.core.errors import NotFoundError

from .common import get_ctx

profile_app = typer.Typer(help="Manage configuration profiles.", no_args_is_help=True)


@profile_app.command("create")
def profile_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Profile name (e.g. creator, coding, private).")],
    provider: Annotated[str | None, typer.Option("--provider", "-p")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m")] = None,
    local_only: Annotated[bool | None, typer.Option("--local-only/--no-local-only")] = None,
) -> None:
    """Create (or overwrite) a profile."""
    app = get_ctx(ctx)
    app.config.config.profiles[name] = ProfileConfig(
        provider=provider, model=model, local_only=local_only
    )
    app.save_config()
    app.ui.success(f"Profile '{name}' created.")


@profile_app.command("use")
def profile_use(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Profile to activate.")],
) -> None:
    """Set the active profile."""
    app = get_ctx(ctx)
    if name not in app.config.config.profiles:
        raise NotFoundError(
            f"No profile named '{name}'.", hint="Create it with `sobai profile create`."
        )
    app.config.config.active_profile = name
    app.save_config()
    app.ui.success(f"Active profile set to '{name}'.")


@profile_app.command("list")
def profile_list(ctx: typer.Context) -> None:
    """List profiles."""
    app = get_ctx(ctx)
    cfg = app.config.config
    if app.ui.json_mode:
        app.ui.print_json(
            {
                "active_profile": cfg.active_profile,
                "profiles": {k: v.model_dump() for k, v in cfg.profiles.items()},
            }
        )
        return
    rows = [
        [
            name,
            p.provider or "-",
            p.model or "-",
            "yes" if p.local_only else ("no" if p.local_only is not None else "-"),
            "*" if name == cfg.active_profile else "",
        ]
        for name, p in cfg.profiles.items()
    ]
    if rows:
        app.ui.table("Profiles", ["name", "provider", "model", "local-only", "active"], rows)
    else:
        app.ui.print("[muted]No profiles. Create one with `sobai profile create <name>`.[/muted]")


@profile_app.command("delete")
def profile_delete(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Profile to delete.")],
) -> None:
    """Delete a profile."""
    app = get_ctx(ctx)
    if name not in app.config.config.profiles:
        raise NotFoundError(f"No profile named '{name}'.")
    del app.config.config.profiles[name]
    if app.config.config.active_profile == name:
        app.config.config.active_profile = None
    app.save_config()
    app.ui.success(f"Profile '{name}' deleted.")
