"""``sobai init`` — guided first-run setup (no manual config editing).

Subscription-authenticated CLIs (Claude Code, Codex) are first-class defaults.
Direct Anthropic/OpenAI API access is an optional, clearly-labeled "separate
metered billing" choice. Setup is idempotent and preserves existing config,
aliases, and profiles.
"""

from __future__ import annotations

import shutil
import subprocess

import typer

from sobai.core.errors import SobaiError
from sobai.providers import cli_status
from sobai.providers.ollama import OllamaProvider
from sobai.providers.registry import build_provider, cred_key

from .common import get_ctx, run_async

# Friendly alias -> the installed Ollama model it should map to, when present.
_OLLAMA_ALIAS_HINTS = {
    "qwen7b": "qwen2.5-coder:7b",
    "qwen14b": "qwen2.5-coder:14b",
    "qwen30b": "qwen3-coder:30b",
}

# Subscription CLI -> its logical alias (value uses the documented `default` sentinel).
_SUBSCRIPTION_ALIASES = {
    "claude-cli": "claude-subscription",
    "codex-cli": "codex-subscription",
}

_LOGIN_ARGV = {
    "claude-cli": ["auth", "login"],
    "codex-cli": ["login"],
}


# --------------------------------------------------------------------------- #
# detection helpers
# --------------------------------------------------------------------------- #
def _discover_ollama(app) -> list[str]:  # type: ignore[no-untyped-def]
    pconf = app.config.config.providers.get("ollama")
    base_url = (pconf.base_url if pconf else None) or "http://localhost:11434"
    provider = OllamaProvider(base_url=base_url)

    async def _go() -> list[str]:
        try:
            return [m.id for m in await provider.list_models()]
        finally:
            await provider.aclose()

    try:
        return run_async(_go())
    except SobaiError:
        return []


def _auto_ollama_aliases(app, installed: list[str]) -> list[str]:  # type: ignore[no-untyped-def]
    created: list[str] = []
    for alias, model in _OLLAMA_ALIAS_HINTS.items():
        if model in installed and alias not in app.config.config.models:
            app.config.config.models[alias] = f"ollama:{model}"
            created.append(alias)
    return created


def _seed_subscription_alias(app, provider: str) -> str:  # type: ignore[no-untyped-def]
    """Ensure the subscription alias exists (idempotent; preserves a user override)."""
    alias = _SUBSCRIPTION_ALIASES[provider]
    app.config.config.models.setdefault(alias, f"{provider}:default")
    return alias


def _select_subscription(app, provider: str) -> None:  # type: ignore[no-untyped-def]
    alias = _seed_subscription_alias(app, provider)
    app.config.config.active_provider = provider
    app.config.config.active_model = alias


def _cli_login(app, provider: str) -> bool:  # type: ignore[no-untyped-def]
    """Launch the CLI's own interactive login after explicit confirmation."""
    exe = shutil.which("claude" if provider == "claude-cli" else "codex")
    if not exe:
        app.ui.warn(f"{provider}: executable not found.")
        return False
    if not typer.confirm(
        f"Launch '{exe} {' '.join(_LOGIN_ARGV[provider])}' to log in now?", default=False
    ):
        app.ui.info("Login skipped.")
        return False
    try:
        # Inherit stdio so the CLI's own browser/device login flow works.
        proc = subprocess.run([exe, *_LOGIN_ARGV[provider]], check=False)  # noqa: S603
    except KeyboardInterrupt:
        app.ui.warn("Login cancelled.")
        return False
    except OSError as exc:
        app.ui.warn(f"Login failed to start: {exc}")
        return False
    return proc.returncode == 0


# --------------------------------------------------------------------------- #
# direct API (advanced)
# --------------------------------------------------------------------------- #
def _store_api_key(app, name: str, label: str) -> bool:  # type: ignore[no-untyped-def]
    key = typer.prompt(f"  {label} API key", hide_input=True).strip()
    if not key:
        app.ui.info(f"  No key entered; skipping {label}.")
        return False
    app.creds.set(cred_key(name), key)
    app.ui.success(f"  Stored {label} API key in the keyring (separate metered billing).")
    try:
        provider = build_provider(name, app.config.config, app.creds)

        async def _go() -> list[str]:
            try:
                return [m.id for m in await provider.list_models()]
            finally:
                await provider.aclose()

        models = run_async(_go())
    except SobaiError as exc:
        app.ui.warn(f"  Could not list models ({exc.message}); set one later with `model use`.")
        models = []
    if models:
        app.ui.print(f"  [muted]available (sample):[/muted] {', '.join(models[:10])}")
    default = typer.prompt(
        f"  Default {label} model id (blank to skip)", default="", show_default=False
    ).strip()
    if default:
        pconf = app.config.config.providers.get(name)
        if pconf:
            pconf.default_model = default
        app.config.config.active_provider = name
        app.config.config.active_model = f"{name}:{default}"
    else:
        app.config.config.active_provider = name
    return True


def _configure_direct_api(app) -> None:  # type: ignore[no-untyped-def]
    app.ui.print("\n[heading]Direct API access[/heading] — separate metered billing:")
    app.ui.print("  1. Anthropic API — separate metered billing")
    app.ui.print("  2. OpenAI API — separate metered billing")
    choice = typer.prompt("Which API", default="1").strip()
    if choice == "1":
        _store_api_key(app, "anthropic", "Anthropic")
    elif choice == "2":
        _store_api_key(app, "openai", "OpenAI")
    else:
        app.ui.info("No API configured.")


# --------------------------------------------------------------------------- #
# detected-access summary
# --------------------------------------------------------------------------- #
def _render_detected(app, ollama_models, claude, codex) -> None:  # type: ignore[no-untyped-def]
    from sobai.core.redaction import redact

    app.ui.rule("Detected model access")

    def line(ok: bool, label: str, detail: str) -> None:
        mark = "[success]✓[/success]" if ok else "[muted]○[/muted]"
        app.ui.print(f"  {mark} [heading]{label:<13}[/heading] {redact(detail)}")

    line(
        bool(ollama_models),
        "Ollama",
        f"installed, {len(ollama_models)} local models" if ollama_models else "not reachable",
    )
    line(
        claude.authenticated, "Claude Code", claude.detail if claude.installed else "not installed"
    )
    line(codex.authenticated, "Codex CLI", codex.detail if codex.installed else "not installed")
    line(
        app.creds.has(cred_key("anthropic")),
        "Anthropic API",
        "configured"
        if app.creds.has(cred_key("anthropic"))
        else "not configured — separate metered billing",
    )
    line(
        app.creds.has(cred_key("openai")),
        "OpenAI API",
        "configured"
        if app.creds.has(cred_key("openai"))
        else "not configured — separate metered billing",
    )


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def init(ctx: typer.Context) -> None:
    """Set up providers and defaults (subscription CLIs first)."""
    app = get_ctx(ctx)
    app.paths.ensure()
    interactive = app.ui.is_interactive() and not app.ui.json_mode

    ollama_models = _discover_ollama(app)
    claude = cli_status.detect_claude_cli()
    codex = cli_status.detect_codex_cli()

    if not interactive:
        _init_non_interactive(app, ollama_models, claude, codex)
        return

    _render_detected(app, ollama_models, claude, codex)

    # Build the dynamic menu, subscription CLIs first.
    options: list[tuple[str, tuple[str, str]]] = []  # (label, (kind, target))
    if codex.authenticated:
        options.append(("Codex CLI (ChatGPT subscription)", ("sub", "codex-cli")))
    if claude.authenticated:
        options.append(("Claude Code CLI (Claude subscription)", ("sub", "claude-cli")))
    if codex.installed and not codex.authenticated:
        options.append(("Log in to Codex CLI (ChatGPT)", ("login", "codex-cli")))
    if claude.installed and not claude.authenticated:
        options.append(("Log in to Claude Code CLI (Claude)", ("login", "claude-cli")))
    if ollama_models:
        options.append(("Ollama (local)", ("ollama", "")))
    options.append(("Configure direct API access", ("api", "")))

    app.ui.print("\n[heading]Choose your default:[/heading]")
    for i, (label, _) in enumerate(options, start=1):
        app.ui.print(f"  {i}. {label}")
    raw = typer.prompt("Select", default="1").strip()
    try:
        idx = int(raw) - 1
        _, action = options[idx]
    except (ValueError, IndexError):
        raise SobaiError("Invalid selection.", hint="Choose one of the listed numbers.") from None

    kind, target = action
    if kind == "sub":
        _select_subscription(app, target)
        app.ui.success(f"Default set to {target} (subscription).")
    elif kind == "login":
        if _cli_login(app, target):
            status = (
                cli_status.detect_claude_cli()
                if target == "claude-cli"
                else cli_status.detect_codex_cli()
            )
            if status.authenticated:
                _select_subscription(app, target)
                app.ui.success(f"Logged in; default set to {target} (subscription).")
            else:
                app.ui.warn(f"{target} still not authenticated; default unchanged.")
    elif kind == "ollama":
        created = _auto_ollama_aliases(app, ollama_models)
        app.config.config.active_provider = "ollama"
        qwen = [a for a in app.config.config.models if a in _OLLAMA_ALIAS_HINTS]
        if qwen:
            app.config.config.active_model = qwen[-1]
        if created:
            app.ui.print(f"  Created aliases: {', '.join(created)}")
        app.ui.success("Default set to ollama (local).")
    elif kind == "api":
        _configure_direct_api(app)

    # Always keep subscription aliases available for authenticated CLIs.
    if claude.authenticated:
        _seed_subscription_alias(app, "claude-cli")
    if codex.authenticated:
        _seed_subscription_alias(app, "codex-cli")

    app.save_config()
    app.ui.rule("Done")
    app.ui.success("Setup complete.")
    app.ui.print("Next steps:")
    app.ui.print("  • [info]sobai doctor[/info] — verify providers, auth, and keyring")
    app.ui.print('  • [info]sobai ask "hello"[/info] — try your default')
    app.ui.print("  • [info]sobai usage[/info] — see token usage and billing mode")


def _init_non_interactive(app, ollama_models, claude, codex) -> None:  # type: ignore[no-untyped-def]
    """Detect and seed aliases without ever launching a browser or login flow."""
    _auto_ollama_aliases(app, ollama_models)
    if claude.authenticated:
        _seed_subscription_alias(app, "claude-cli")
    if codex.authenticated:
        _seed_subscription_alias(app, "codex-cli")

    # Choose a default only if none is set: subscription CLIs first, then local.
    if not app.config.config.active_provider:
        if codex.authenticated:
            _select_subscription(app, "codex-cli")
        elif claude.authenticated:
            _select_subscription(app, "claude-cli")
        elif ollama_models:
            app.config.config.active_provider = "ollama"
            qwen = [a for a in app.config.config.models if a in _OLLAMA_ALIAS_HINTS]
            if qwen and not app.config.config.active_model:
                app.config.config.active_model = qwen[-1]
    app.save_config()

    summary = {
        "ollama_models": len(ollama_models),
        "claude_cli": claude.detail,
        "codex_cli": codex.detail,
        "active_provider": app.config.config.active_provider,
        "active_model": app.config.config.active_model,
    }
    if app.ui.json_mode:
        app.ui.print_json(summary)
    else:
        app.ui.info(
            f"Non-interactive init: ollama={summary['ollama_models']} models, "
            f"claude-cli={claude.detail}, codex-cli={codex.detail}, "
            f"default={summary['active_provider']}. No login flow was launched."
        )
