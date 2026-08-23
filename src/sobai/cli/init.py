"""``sobai init`` — guided first-run setup (no manual config editing)."""

from __future__ import annotations

import typer

from sobai.core.errors import SobaiError
from sobai.providers.ollama import OllamaProvider
from sobai.providers.registry import build_provider, cred_key

from .common import get_ctx, run_async

# Friendly alias -> the installed Ollama model it should map to, when present.
_OLLAMA_ALIAS_HINTS = {
    "qwen7b": "qwen2.5-coder:7b",
    "qwen14b": "qwen2.5-coder:14b",
    "qwen30b": "qwen3-coder:30b",
}


def _discover_ollama(app) -> list[str]:  # type: ignore[no-untyped-def]
    pconf = app.config.config.providers.get("ollama")
    base_url = (pconf.base_url if pconf else None) or "http://localhost:11434"
    provider = OllamaProvider(base_url=base_url)

    async def _go() -> list[str]:
        try:
            models = await provider.list_models()
        finally:
            await provider.aclose()
        return [m.id for m in models]

    try:
        return run_async(_go())
    except SobaiError:
        return []


def _auto_ollama_aliases(app, installed: list[str]) -> list[str]:  # type: ignore[no-untyped-def]
    created: list[str] = []
    for alias, model in _OLLAMA_ALIAS_HINTS.items():
        if model in installed:
            app.config.config.models[alias] = f"ollama:{model}"
            created.append(alias)
    return created


def _setup_api_provider(app, name: str, label: str) -> bool:  # type: ignore[no-untyped-def]
    """Interactively configure an API-key provider. Returns True if configured."""
    if not typer.confirm(f"Configure {label} API access?", default=False):
        return False
    key = typer.prompt(f"  {label} API key", hide_input=True).strip()
    if not key:
        app.ui.info(f"  No key entered; skipping {label}.")
        return False
    app.creds.set(cred_key(name), key)
    app.ui.success(f"  Stored {label} API key in the keyring.")
    # Best-effort model discovery to help choose a default.
    try:
        provider = build_provider(name, app.config.config, app.creds)

        async def _go() -> list[str]:
            try:
                return [m.id for m in await provider.list_models()]
            finally:
                await provider.aclose()

        models = run_async(_go())
    except SobaiError as exc:
        app.ui.warn(f"  Could not list models ({exc.message}). You can set one later.")
        models = []
    if models:
        preview = ", ".join(models[:10])
        app.ui.print(f"  [muted]available (sample):[/muted] {preview}")
    default = typer.prompt(
        f"  Default {label} model id (blank to skip)", default="", show_default=False
    ).strip()
    if default:
        pconf = app.config.config.providers.get(name)
        if pconf:
            pconf.default_model = default
        return True
    return bool(models) or True


def init(ctx: typer.Context) -> None:
    """Set up providers and defaults interactively."""
    app = get_ctx(ctx)
    interactive = app.ui.is_interactive() and not app.ui.json_mode

    app.paths.ensure()
    configured: list[str] = []

    if not interactive:
        # Non-interactive: write defaults and auto-detect local Ollama models.
        installed = _discover_ollama(app)
        created = _auto_ollama_aliases(app, installed)
        if installed:
            app.config.config.active_provider = app.config.config.active_provider or "ollama"
            if created and not app.config.config.active_model:
                app.config.config.active_model = created[-1]
        app.save_config()
        app.ui.info(
            f"Wrote default config to {app.paths.config_file}. "
            f"Ollama models detected: {len(installed)}; aliases: {', '.join(created) or 'none'}."
        )
        app.ui.info("Run `sobai init` in an interactive terminal to configure cloud providers.")
        return

    app.ui.rule("SoBatista AI setup")
    app.ui.print("Credentials are stored in your OS keyring — never in files.\n")

    if _setup_api_provider(app, "anthropic", "Anthropic (Claude)"):
        configured.append("anthropic")
    if _setup_api_provider(app, "openai", "OpenAI"):
        configured.append("openai")

    # Ollama (local) — auto-detect and offer aliases.
    installed = _discover_ollama(app)
    if installed:
        app.ui.success(f"Ollama reachable — {len(installed)} model(s) installed.")
        created = _auto_ollama_aliases(app, installed)
        if created:
            app.ui.print(f"  Created aliases: {', '.join(created)}")
        configured.append("ollama")
    else:
        app.ui.info("Ollama not reachable (start it with `ollama serve` to use local models).")

    # Choose active provider/model.
    if configured:
        default_provider = configured[0]
        chosen = typer.prompt(
            f"Active provider ({'/'.join(configured)})", default=default_provider
        ).strip()
        if chosen in configured or chosen in app.config.config.providers:
            app.config.config.active_provider = chosen
            pconf = app.config.config.providers.get(chosen)
            if pconf and pconf.default_model:
                app.config.config.active_model = f"{chosen}:{pconf.default_model}"
            elif chosen == "ollama":
                aliases = [a for a in app.config.config.models if a.startswith("qwen")]
                if aliases:
                    app.config.config.active_model = aliases[-1]

    app.save_config()
    app.ui.rule("Done")
    app.ui.success("Setup complete.")
    app.ui.print("Next steps:")
    app.ui.print("  • [info]sobai doctor[/info] — verify providers and keyring")
    app.ui.print('  • [info]sobai ask "hello"[/info] — try a prompt')
    app.ui.print("  • [info]sobai aliases install bash[/info] — install shell shortcuts")
