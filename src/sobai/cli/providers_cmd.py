"""Provider and model management commands."""

from __future__ import annotations

from typing import Annotated

import typer

from sobai.core.context import AppContext
from sobai.core.errors import ConfigError, NotFoundError
from sobai.providers.registry import (
    ALL_PROVIDERS,
    billing_mode,
    build_provider,
    canonical_provider,
    cred_key,
    resolve_model_ref,
)

from .common import get_ctx, run_async

# Providers that authenticate with an API key stored in the keyring.
API_KEY_PROVIDERS = ("anthropic", "openai")
# Connectors handled by the dedicated connector module (later phase).
KNOWN_CONNECTORS = ("youtube", "notion")

providers_app = typer.Typer(help="Inspect available model providers.", no_args_is_help=True)
models_app = typer.Typer(help="List and discover models and aliases.", no_args_is_help=True)


def _auth_summary(app: AppContext, name: str) -> str:
    """A short, non-identifying auth summary for a provider."""
    from sobai.core.redaction import redact
    from sobai.providers import cli_status

    if name in API_KEY_PROVIDERS:
        return "key stored" if app.creds.has(cred_key(name)) else "no key"
    if name == "claude-cli":
        return redact(cli_status.detect_claude_cli().detail)
    if name == "codex-cli":
        return redact(cli_status.detect_codex_cli().detail)
    return "n/a"


@providers_app.command("list")
def providers_list(ctx: typer.Context) -> None:
    """List configured providers with billing mode and authentication status."""
    app = get_ctx(ctx)
    cfg = app.config.config
    rows: list[list[str]] = []
    data: list[dict[str, object]] = []
    for name in ALL_PROVIDERS:
        pconf = cfg.providers.get(name)
        billing = billing_mode(name)
        auth = _auth_summary(app, name)
        enabled = "yes" if (pconf.enabled if pconf else True) else "no"
        base = (pconf.base_url if pconf else None) or "-"
        default_model = (pconf.default_model if pconf else None) or "-"
        rows.append([name, billing, enabled, auth, base, default_model])
        data.append(
            {
                "name": name,
                "billing_mode": billing,
                "enabled": pconf.enabled if pconf else True,
                "auth": auth,
                "base_url": base,
                "default_model": default_model,
            }
        )
    if app.ui.json_mode:
        app.ui.print_json({"active_provider": cfg.active_provider, "providers": data})
        return
    app.ui.table(
        "Providers",
        ["name", "billing", "enabled", "auth", "base_url", "default_model"],
        rows,
    )
    if cfg.active_provider:
        app.ui.print(f"[muted]active provider:[/muted] {cfg.active_provider}")


@models_app.command("list")
def models_list(ctx: typer.Context) -> None:
    """List logical model aliases and the active model."""
    app = get_ctx(ctx)
    cfg = app.config.config
    rows = [[alias, target] for alias, target in sorted(cfg.models.items())]
    if app.ui.json_mode:
        app.ui.print_json({"active_model": cfg.active_model, "aliases": cfg.models})
        return
    if rows:
        app.ui.table("Model aliases", ["alias", "target (provider:model)"], rows)
    else:
        app.ui.print("[muted]No model aliases configured. Run `sobai init` to set some up.[/muted]")
    app.ui.print(f"[muted]active model:[/muted] {cfg.active_model or '(none)'}")


@models_app.command("discover")
def models_discover(
    ctx: typer.Context,
    provider: Annotated[
        str, typer.Option("--provider", "-p", help="Provider to query for models.")
    ],
) -> None:
    """Discover models a provider currently offers (live query)."""
    app = get_ctx(ctx)
    canon = canonical_provider(provider)
    app.policy.assert_provider_permitted(canon)
    prov = build_provider(canon, app.config.config, app.creds)

    async def _go() -> list[dict[str, str | None]]:
        try:
            models = await prov.list_models()
        finally:
            await prov.aclose()
        return [{"id": m.id, "display_name": m.display_name} for m in models]

    models = run_async(_go())
    if app.ui.json_mode:
        app.ui.print_json({"provider": canon, "models": models})
        return
    rows = [[m["id"] or "", m["display_name"] or ""] for m in models]
    app.ui.table(f"Models — {canon}", ["id", "display name"], rows)
    app.ui.print(
        f"[muted]{len(models)} model(s). Set one with `sobai model use {canon}:<id>`.[/muted]"
    )


provider_app = typer.Typer(help="Select the active provider.", no_args_is_help=True)
model_app = typer.Typer(help="Select the active model.", no_args_is_help=True)


@provider_app.command("use")
def provider_use(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Provider name or alias (e.g. claude).")],
) -> None:
    """Set the active provider."""
    app = get_ctx(ctx)
    canon = canonical_provider(name)
    app.config.config.active_provider = canon
    app.save_config()
    app.ui.success(f"Active provider set to '{canon}'.")


@model_app.command("use")
def model_use(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="Model alias or provider:model id.")],
) -> None:
    """Set the active model (alias or provider-qualified id)."""
    app = get_ctx(ctx)
    resolved_provider, model_id = resolve_model_ref(app.config.config, ref)
    app.config.config.active_model = ref
    if resolved_provider:
        app.config.config.active_provider = resolved_provider
    app.save_config()
    where = f" (provider '{resolved_provider}', model '{model_id}')" if resolved_provider else ""
    app.ui.success(f"Active model set to '{ref}'{where}.")


def connect_command(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Provider (anthropic|openai) or connector.")],
    monetary: Annotated[
        bool, typer.Option("--monetary", help="YouTube: also request revenue analytics scope.")
    ] = False,
    captions: Annotated[
        bool, typer.Option("--captions", help="YouTube: also request caption access (broad scope).")
    ] = False,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="YouTube: print the auth URL instead of opening it."),
    ] = False,
) -> None:
    """Store credentials for a provider (or start a connector auth flow).

    API keys are read via a hidden prompt and stored in the OS keyring — never in
    files, arguments, or shell history.
    """
    app = get_ctx(ctx)
    name = target.lower()
    if name == "youtube":
        from .youtube_cmd import connect_youtube

        connect_youtube(app, monetary=monetary, captions=captions, no_browser=no_browser)
        return
    if name in KNOWN_CONNECTORS:
        raise NotFoundError(
            f"Connector '{name}' setup is not available in this build yet.",
            hint=f"`sobai connect {name}` arrives with the {name} connector.",
        )
    try:
        canon = canonical_provider(name)
    except ConfigError as exc:
        raise NotFoundError(
            f"Unknown provider or connector '{target}'.",
            hint="Providers: anthropic, openai. Connectors: youtube, notion.",
        ) from exc
    if canon not in API_KEY_PROVIDERS:
        raise NotFoundError(
            f"Provider '{canon}' does not use a stored API key.",
            hint="Ollama needs no key; CLI bridges use their own login.",
        )
    key = typer.prompt(f"Enter {canon} API key", hide_input=True)
    if not key.strip():
        raise ConfigError("Empty key; nothing stored.")
    app.creds.set(cred_key(canon), key.strip())
    app.ui.success(f"Stored {canon} API key in the OS keyring.")


def disconnect_command(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Provider or connector to disconnect.")],
) -> None:
    """Remove stored credentials for a provider or connector."""
    app = get_ctx(ctx)
    name = target.lower()
    if name == "youtube":
        from .youtube_cmd import disconnect_youtube

        disconnect_youtube(app)
        return
    if name in KNOWN_CONNECTORS:
        raise NotFoundError(
            f"Connector '{name}' is not available in this build yet.",
            hint=f"`sobai disconnect {name}` arrives with the {name} connector.",
        )
    canon = canonical_provider(name)
    removed = app.creds.delete(cred_key(canon))
    if removed:
        app.ui.success(f"Removed stored credential for '{canon}'.")
    else:
        app.ui.info(f"No stored credential for '{canon}'.")
