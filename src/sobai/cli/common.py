"""Shared helpers for CLI command modules."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Literal

import typer

from sobai.core.context import AppContext
from sobai.core.errors import PolicyError
from sobai.core.types import Usage
from sobai.policies import EgressAction, EgressDecision
from sobai.providers.base import Provider
from sobai.providers.cli_bridge import CLI_DEFAULT_MODEL
from sobai.providers.registry import billing_mode, build_provider
from sobai.ui.console import UI


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


#: Where a prompt came from. This is metadata about the invocation, not about
#: what was asked, which is why it is safe to keep in run history.
PromptSource = Literal["argument", "stdin", "interactive"]


@dataclass(frozen=True, slots=True)
class PromptText:
    """A user-supplied prompt, carrying its own shape so nothing has to re-derive it.

    Commands need the text to send and, separately, a way to describe the run
    without quoting it. Keeping both together is what stops a caller from
    reaching for ``text[:200]`` because the size was not to hand.
    """

    text: str
    source: PromptSource

    @property
    def byte_size(self) -> int:
        """UTF-8 size — the encoding that actually travels to a provider."""
        return len(self.text.encode("utf-8"))

    @property
    def char_size(self) -> int:
        return len(self.text)


def history_summary(command: str, prompt: PromptText) -> str:
    """Build the content-free run-history summary for a model-backed command.

    Run history is long-lived local state. It records *that* a prompt was sent,
    from where, and how big it was — never any part of it. Development builds
    before 0.2.0 stored ``text[:200]``, which put the opening of every question
    on disk where `sobai history`, `runs show`, and any later reader could see
    it; see PRIVACY.md for how to clear a database written by one of those.

    A digest is deliberately not recorded either. A hash cannot be reversed, but
    a short or predictable prompt can simply be guessed and confirmed against
    it, and nothing in Phase 1 needs to correlate two runs by content.
    """
    return f"{command} · {prompt.source} · {prompt.byte_size} bytes · {prompt.char_size} chars"


@dataclass(slots=True)
class ModelOutput:
    """Render a model's answer exactly once, however the provider delivered it.

    Providers arrive in two shapes. Some emit text deltas and then a completion
    that repeats the whole answer; the CLI bridges (``claude-cli``,
    ``codex-cli``) and some one-shot HTTP endpoints return the finished answer
    having emitted no deltas at all. Printing the accumulated text
    unconditionally duplicates the first kind, and printing only deltas loses
    the second entirely — so the rule is to remember whether a non-empty delta
    actually arrived, and render whichever happened.

    Sanitization is unchanged and belongs to :class:`~sobai.ui.console.UI`:
    deltas go through ``stream_write`` and one-shot text through
    ``print_untrusted``, which strip terminal escapes, stray control bytes, and
    Unicode bidi controls. Both are no-ops in JSON mode, so this can never
    contaminate the machine-readable document.
    """

    ui: UI
    #: True once a non-empty delta has been written. An empty delta is not
    #: output, and must not suppress the final text.
    streamed: bool = False

    def on_text(self, chunk: str) -> None:
        """Provider callback for one streamed text delta."""
        if not chunk:
            return
        self.streamed = True
        self.ui.stream_write(chunk)

    def finish(self, text: str) -> None:
        """Terminate streamed output, or print an answer that never streamed."""
        if self.streamed:
            self.ui.stream_end()
        elif text:
            self.ui.print_untrusted(text)


def read_prompt_arg(prompt: list[str] | None) -> PromptText:
    """Join prompt words, or read from stdin when piped / given '-'."""
    text = " ".join(prompt).strip() if prompt else ""
    source: PromptSource = "argument"
    if text in ("", "-") and not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            text = piped if text == "" else f"{text}\n{piped}"
            source = "stdin"
    if not text or text == "-":
        raise typer.BadParameter("No prompt provided (pass text or pipe via stdin).")
    return PromptText(text=text, source=source)


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
