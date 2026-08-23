"""Shared helpers for CLI command modules."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

import typer

from sobai.core.context import AppContext
from sobai.core.errors import PolicyError
from sobai.policies import EgressAction, EgressDecision
from sobai.providers.base import Provider
from sobai.providers.registry import build_provider


def get_ctx(ctx: typer.Context) -> AppContext:
    """Fetch the AppContext attached by the root callback."""
    obj = ctx.obj
    if not isinstance(obj, AppContext):  # pragma: no cover - defensive
        raise RuntimeError("Application context was not initialized.")
    return obj


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def resolve_provider(app: AppContext) -> tuple[Provider, str, str]:
    """Resolve selection, enforce local-only, and build the provider.

    Returns ``(provider, provider_name, model_id)``.
    """
    provider_name, model_id = app.selected_provider_model()
    # Hard-fail before constructing anything if --local-only forbids this provider.
    app.policy.assert_provider_permitted(provider_name)
    provider = build_provider(provider_name, app.config.config, app.creds)
    return provider, provider_name, model_id


def read_prompt_arg(prompt: list[str] | None) -> str:
    """Join prompt words, or read from stdin when piped / given '-'."""
    text = " ".join(prompt).strip() if prompt else ""
    if text in ("", "-") and not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            text = piped if text == "" else f"{text}\n{piped}"
    if not text or text == "-":
        raise typer.BadParameter("No prompt provided (pass text or pipe via stdin).")
    return text


def enforce_egress(
    app: AppContext,
    decision: EgressDecision,
    *,
    assume_yes: bool = False,
) -> None:
    """Apply an egress decision, prompting the user when consent is required.

    Raises :class:`PolicyError` if the operation is denied.
    """
    if decision.action is EgressAction.ALLOW:
        return
    if decision.action is EgressAction.DENY:
        raise PolicyError(
            f"Sending '{decision.data_class}' data from "
            f"{decision.connector or 'a connector'} to '{decision.provider}' is denied "
            f"({decision.reason}).",
            hint="Use a local provider (`-p ollama`) or adjust policy.egress in config.",
        )
    # CONSENT
    summary = (
        f"About to send [{decision.data_class}] data from "
        f"'{decision.connector or 'connector'}' to cloud provider '{decision.provider}'."
    )
    if assume_yes:
        app.ui.info(summary + " (auto-approved)")
        return
    if not app.ui.is_interactive():
        raise PolicyError(
            summary + " Cannot prompt for consent in a non-interactive session.",
            hint="Re-run interactively, pass --yes, or set an explicit policy.egress entry.",
        )
    app.ui.warn(summary)
    approved = typer.confirm("Allow this data to leave your machine?", default=False)
    if not approved:
        raise PolicyError("Egress declined by user.", hint="Nothing was sent.")
