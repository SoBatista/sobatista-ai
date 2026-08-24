"""Shared helpers for CLI command modules."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

import typer

from sobai.core.context import AppContext
from sobai.core.errors import PolicyError
from sobai.core.types import Usage
from sobai.policies import EgressAction, EgressDecision
from sobai.providers.base import Provider
from sobai.providers.cli_bridge import CLI_DEFAULT_MODEL
from sobai.providers.registry import billing_mode, build_provider


def recorded_model(model_id: str) -> str:
    """Map the CLI-default sentinel to a readable label for run history."""
    return "provider-default" if model_id == CLI_DEFAULT_MODEL else model_id


def cost_accounting(provider_name: str, usage: Usage) -> tuple[str, float | None, str]:
    """Return (auth/billing mode, cost_usd, cost_kind) for a run.

    cost_kind is one of "actual" (local, $0), "estimated" (a provider-reported
    client-side estimate), or "unavailable" (no monetary figure available — e.g.
    Codex subscription, or a metered API we do not price locally).
    """
    mode = billing_mode(provider_name)
    if mode == "local":
        return mode, 0.0, "actual"
    if usage.cost_usd is not None:
        return mode, usage.cost_usd, "estimated"
    return mode, None, "unavailable"


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
    subject: str | None = None,
    detail: str | None = None,
    consent_hint: str | None = None,
) -> None:
    """Apply an egress decision, prompting the user when consent is required.

    ``subject`` names what the data is (defaulting to the connector), and
    ``detail`` adds context lines shown before the prompt — for a Skill run,
    which skill, which model, and which input. Raises :class:`PolicyError` if
    the operation is denied.
    """
    if decision.action is EgressAction.ALLOW:
        return
    origin = subject or f"'{decision.connector or 'connector'}'"
    if decision.action is EgressAction.DENY:
        raise PolicyError(
            f"Sending '{decision.data_class}' data from {origin} to "
            f"'{decision.provider}' is denied ({decision.reason}).",
            hint="Use a local provider (`-p ollama`) or adjust policy.egress in config.",
        )
    # CONSENT
    summary = (
        f"About to send [{decision.data_class}] data from {origin} "
        f"to cloud provider '{decision.provider}'."
    )
    if assume_yes:
        app.ui.info(summary + " (auto-approved)")
        return
    if not app.ui.is_interactive():
        raise PolicyError(
            summary + " Cannot prompt for consent in a non-interactive session.",
            hint=consent_hint
            or "Re-run interactively, pass --yes, or set an explicit policy.egress entry.",
        )
    app.ui.warn(summary)
    if detail:
        app.ui.info(detail)
    approved = typer.confirm("Allow this data to leave your machine?", default=False)
    if not approved:
        raise PolicyError("Egress declined by user.", hint="Nothing was sent.")
