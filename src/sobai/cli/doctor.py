"""``sobai doctor`` — diagnose environment, keyring, providers, and connectors."""

from __future__ import annotations

import platform

import typer

from sobai import __version__
from sobai.core.errors import SobaiError
from sobai.providers.base import ProviderHealth
from sobai.providers.registry import (
    ALL_PROVIDERS,
    build_provider,
    cred_key,
)

from .common import get_ctx, run_async
from .providers_cmd import API_KEY_PROVIDERS, KNOWN_CONNECTORS


async def _probe(app, name: str) -> ProviderHealth:  # type: ignore[no-untyped-def]
    # Skip building cloud providers with no credential; report cleanly instead.
    if name in API_KEY_PROVIDERS and not app.creds.has(cred_key(name)):
        return ProviderHealth(provider=name, ok=False, detail="no API key stored (optional)")
    try:
        provider = build_provider(name, app.config.config, app.creds)
    except SobaiError as exc:
        return ProviderHealth(provider=name, ok=False, detail=exc.message)
    try:
        return await provider.health()
    except SobaiError as exc:
        return ProviderHealth(provider=name, ok=False, detail=exc.message)
    finally:
        await provider.aclose()


def doctor(ctx: typer.Context) -> None:
    """Run diagnostics across environment, keyring, providers, and connectors."""
    app = get_ctx(ctx)
    keyring_status = app.creds.status()

    async def _all() -> list[ProviderHealth]:
        import asyncio

        return await asyncio.gather(*(_probe(app, n) for n in ALL_PROVIDERS))

    healths = run_async(_all())

    env = {
        "sobai_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "config_file": str(app.paths.config_file),
        "config_exists": app.paths.config_file.exists(),
        "state_db": str(app.paths.state_db),
    }
    connectors = {
        name: ("connected" if app.config.config.connectors.get(name) else "not connected")
        for name in KNOWN_CONNECTORS
    }

    if app.ui.json_mode:
        app.ui.print_json(
            {
                "environment": env,
                "keyring": {
                    "backend": keyring_status.backend,
                    "usable": keyring_status.usable,
                    "detail": keyring_status.detail,
                },
                "providers": [
                    {"provider": h.provider, "ok": h.ok, "detail": h.detail, "models": h.models}
                    for h in healths
                ],
                "connectors": connectors,
            }
        )
        return

    app.ui.rule("Environment")
    for key, value in env.items():
        app.ui.print(f"  [heading]{key}[/heading]: {value}")

    app.ui.rule("Keyring")
    mark = "[success]✓[/success]" if keyring_status.usable else "[error]✗[/error]"
    app.ui.print(f"  {mark} {keyring_status.backend}")
    app.ui.print(f"    [muted]{keyring_status.detail}[/muted]")

    app.ui.rule("Providers")
    for h in healths:
        mark = "[success]✓[/success]" if h.ok else "[warn]•[/warn]"
        app.ui.print(f"  {mark} [heading]{h.provider}[/heading]: {h.detail}")
        if h.models:
            app.ui.print(f"    [muted]models: {', '.join(h.models)}[/muted]")

    app.ui.rule("Connectors")
    for name, status in connectors.items():
        app.ui.print(f"  [muted]{name}:[/muted] {status}")
