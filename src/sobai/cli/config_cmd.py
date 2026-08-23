"""Configuration inspection, connections overview, and privacy explainer."""

from __future__ import annotations

from typing import Annotated

import tomli_w
import typer

from sobai.core.redaction import redact
from sobai.providers.registry import ALL_PROVIDERS, cred_key
from sobai.ui.console import render_untrusted

from .common import get_ctx
from .providers_cmd import API_KEY_PROVIDERS, KNOWN_CONNECTORS


def config_show(
    ctx: typer.Context,
    redacted: Annotated[
        bool, typer.Option("--redacted/--raw", help="Redact secret-shaped values (default).")
    ] = True,
) -> None:
    """Show the effective configuration (no secrets are ever stored in it)."""
    app = get_ctx(ctx)
    if app.ui.json_mode:
        app.ui.print_json(app.config.config.model_dump(mode="json"))
        return
    # None is not representable in TOML; drop null keys for the rendered view.
    data = app.config.config.model_dump(mode="json", exclude_none=True)
    text = tomli_w.dumps(data)
    if redacted:
        text = redact(text)
    app.ui.print(f"[muted]# {app.paths.config_file}[/muted]")
    app.ui.print(render_untrusted(text))


def connections(ctx: typer.Context) -> None:
    """Show provider credentials and connector connections at a glance."""
    app = get_ctx(ctx)
    cfg = app.config.config
    prov_rows: list[list[str]] = []
    for name in ALL_PROVIDERS:
        if name in API_KEY_PROVIDERS:
            status = "connected" if app.creds.has(cred_key(name)) else "no key"
        elif name.endswith("-cli"):
            status = "uses CLI login"
        else:
            status = "local (no key)"
        prov_rows.append([name, status])

    conn_rows: list[list[str]] = []
    for name in KNOWN_CONNECTORS:
        meta = cfg.connectors.get(name)
        if meta:
            scopes = ", ".join(meta.scopes) or "-"
            conn_rows.append([name, "connected", meta.account or "-", scopes])
        else:
            conn_rows.append([name, "not connected", "-", "-"])

    if app.ui.json_mode:
        app.ui.print_json(
            {
                "providers": {r[0]: r[1] for r in prov_rows},
                "connectors": {
                    r[0]: {"status": r[1], "account": r[2], "scopes": r[3]} for r in conn_rows
                },
            }
        )
        return
    app.ui.table("Providers", ["provider", "status"], prov_rows)
    app.ui.table("Connectors", ["connector", "status", "account", "scopes"], conn_rows)


def privacy_explain(ctx: typer.Context) -> None:
    """Explain the privacy boundary and current effective policy."""
    app = get_ctx(ctx)
    policy = app.config.config.policy
    if app.ui.json_mode:
        app.ui.print_json(
            {
                "local_only": app.policy.local_only,
                "max_tool_rounds": policy.max_tool_rounds,
                "egress": dict(policy.egress),
                "allowed_connectors": policy.allowed_connectors,
            }
        )
        return
    app.ui.rule("Privacy model")
    app.ui.print(
        "SoBatista AI keeps a clear boundary between your machine and cloud models:\n\n"
        "  • [heading]Credentials[/heading] live only in your OS keyring — never in config, "
        "environment files, shell history, or process arguments.\n"
        "  • [heading]Local providers[/heading] (Ollama) never send data off the machine.\n"
        "  • [heading]--local-only[/heading] hard-fails any operation that would reach a "
        "cloud API.\n"
        "  • [heading]Connector data[/heading] is classified (public / internal / sensitive / "
        "restricted). Before it leaves for a cloud model, you are shown what connector and "
        "class will be sent — unless you've set a persistent policy.\n"
        "  • [heading]External content is untrusted data[/heading], never instructions. It can "
        "never enable tools or change policy.\n"
    )
    app.ui.print(f"[muted]Effective local-only:[/muted] {app.policy.local_only}")
    egress = "  ".join(f"{k}={v}" for k, v in policy.egress.items())
    app.ui.print(f"[muted]Egress policy:[/muted] {egress}")
    app.ui.print(f"[muted]Max tool rounds:[/muted] {policy.max_tool_rounds}")
