"""Console output abstraction.

A single :class:`UI` object carries the presentation mode and routes output
correctly:

* **text mode** — human-readable Rich output on stdout, diagnostics on stderr
* **json mode** — only structured JSON on stdout; all logs/diagnostics on stderr
  and no decorative output (per the automation contract)
* **quiet** — suppress non-essential chatter
* **no-color** — disable ANSI styling (also auto-disabled when not a TTY)

Untrusted external text is always passed through :func:`render_untrusted` before
display: control/escape sequences are stripped and Rich markup is escaped so a
malicious title or page body cannot drive the terminal or inject styling.
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.theme import Theme

from sobai.core.redaction import redact
from sobai.core.safeterm import sanitize

# Accessible, restrained palette (works on light and dark, avoids red/green-only cues).
_THEME = Theme(
    {
        "info": "cyan",
        "warn": "yellow",
        "error": "bold red",
        "success": "bold green",
        "muted": "dim",
        "heading": "bold",
    }
)


class OutputMode(StrEnum):
    TEXT = "text"
    JSON = "json"


def render_untrusted(text: str) -> str:
    """Make external text safe to hand to Rich: strip control seqs, escape markup."""
    return escape(sanitize(text))


class UI:
    def __init__(
        self,
        *,
        mode: OutputMode = OutputMode.TEXT,
        quiet: bool = False,
        no_color: bool = False,
    ) -> None:
        self.mode = mode
        self.quiet = quiet
        self._out = Console(
            theme=_THEME,
            no_color=no_color,
            highlight=False,
            soft_wrap=False,
        )
        self._err = Console(
            theme=_THEME,
            no_color=no_color,
            stderr=True,
            highlight=False,
        )

    @property
    def json_mode(self) -> bool:
        return self.mode is OutputMode.JSON

    # -- diagnostics (always to stderr; suppressed by quiet where noted) ----
    def info(self, message: str) -> None:
        if not self.quiet:
            self._err.print(f"[info]•[/info] {redact(message)}")

    def warn(self, message: str) -> None:
        self._err.print(f"[warn]![/warn] {redact(message)}")

    def error(self, message: str, *, hint: str | None = None) -> None:
        self._err.print(f"[error]✗[/error] {redact(message)}")
        if hint:
            self._err.print(f"  [muted]{redact(hint)}[/muted]")

    def success(self, message: str) -> None:
        if not self.quiet:
            self._err.print(f"[success]✓[/success] {redact(message)}")

    # -- primary output ----------------------------------------------------
    def print(self, *args: Any, **kwargs: Any) -> None:
        """Human output. Suppressed entirely in JSON mode."""
        if self.json_mode:
            return
        self._out.print(*args, **kwargs)

    def print_untrusted(self, text: str) -> None:
        """Print external/untrusted text safely (text mode only)."""
        if self.json_mode:
            return
        self._out.print(render_untrusted(text))

    def stream_write(self, text: str) -> None:
        """Write a model output chunk to stdout, stripped of control sequences."""
        if self.json_mode:
            return
        sys.stdout.write(sanitize(redact(text)))
        sys.stdout.flush()

    def stream_end(self) -> None:
        if not self.json_mode:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def print_json(self, data: Any) -> None:
        """Emit a JSON document to stdout (the machine-readable channel)."""
        text = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        # stdout, no Rich styling, so it is pipe-safe.
        print(redact(text))

    def table(self, title: str | None, columns: list[str], rows: list[list[str]]) -> None:
        if self.json_mode:
            return
        table = Table(title=title, title_style="heading", header_style="heading")
        for col in columns:
            table.add_column(col)
        for row in rows:
            table.add_row(*row)
        self._out.print(table)

    def rule(self, title: str = "") -> None:
        if not self.json_mode:
            self._out.rule(title, style="muted")

    # -- prompts -----------------------------------------------------------
    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and sys.stderr.isatty()
