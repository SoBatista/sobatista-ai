"""Detect installed AI CLIs and their authentication mode — safely.

We detect executables with ``shutil.which`` and authentication by invoking the
CLI's own **status** subcommand through a subprocess argv array with a short
timeout:

* ``claude auth status``
* ``codex login status``

We **never** read, copy, or parse credential files (e.g. ``~/.claude/.credentials.json``,
``~/.codex/auth.json``), never import CLI credentials into SoBatista's keyring, and
never expose account identities (email/org). A subscription tier is reported only
when the status output explicitly states one. All captured output is redacted.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from sobai.core.redaction import redact

# Detection status commands (argv arrays — never a shell string).
_CLAUDE_STATUS = ["auth", "status"]
_CODEX_STATUS = ["login", "status"]
_TIMEOUT_S = 15.0


@dataclass(frozen=True, slots=True)
class CliAuthStatus:
    name: str  # "claude-cli" | "codex-cli"
    executable: str
    installed: bool
    authenticated: bool
    #: "subscription" | "api-key" | "unknown" | None
    mode: str | None
    #: Short, non-identifying description (safe to display).
    detail: str
    #: Subscription tier, only when the status output explicitly reports one.
    tier: str | None = None


def _run(argv: list[str], *, timeout: float = _TIMEOUT_S) -> tuple[int, str, str]:
    """Run a status command with no stdin and a timeout. Returns (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv array, no shell, fixed commands
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except OSError as exc:  # pragma: no cover - environment dependent
        return 127, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def detect_claude_cli() -> CliAuthStatus:
    exe = shutil.which("claude")
    if not exe:
        return CliAuthStatus(
            name="claude-cli",
            executable="claude",
            installed=False,
            authenticated=False,
            mode=None,
            detail="not installed",
        )
    rc, out, err = _run([exe, *_CLAUDE_STATUS])
    if rc == 124:
        return CliAuthStatus(
            name="claude-cli",
            executable=exe,
            installed=True,
            authenticated=False,
            mode="unknown",
            detail="status check timed out",
        )
    # Preferred: JSON output. We extract only non-identifying fields.
    data = _try_json(out)
    if data is not None:
        logged_in = bool(data.get("loggedIn"))
        auth_method = str(data.get("authMethod", "")).lower()
        subscription = auth_method in ("claude.ai", "subscription", "oauth")
        mode = "subscription" if subscription else ("api-key" if logged_in else None)
        tier = data.get("subscriptionType") if subscription else None
        detail = (
            "authenticated via Claude subscription"
            if mode == "subscription"
            else "authenticated via API key"
            if mode == "api-key"
            else "installed but not authenticated"
        )
        if tier:
            detail += f" ({tier})"
        return CliAuthStatus(
            name="claude-cli",
            executable=exe,
            installed=True,
            authenticated=logged_in,
            mode=mode,
            detail=detail,
            tier=str(tier) if tier else None,
        )
    # Fallback: text heuristics (never claim a tier we didn't see).
    text = (out + "\n" + err).lower()
    authed = rc == 0 and "logged in" in text and "not logged in" not in text
    return CliAuthStatus(
        name="claude-cli",
        executable=exe,
        installed=True,
        authenticated=authed,
        mode="subscription" if authed else None,
        detail="authenticated" if authed else "installed but not authenticated",
    )


def detect_codex_cli() -> CliAuthStatus:
    exe = shutil.which("codex")
    if not exe:
        return CliAuthStatus(
            name="codex-cli",
            executable="codex",
            installed=False,
            authenticated=False,
            mode=None,
            detail="not installed",
        )
    rc, out, err = _run([exe, *_CODEX_STATUS])
    if rc == 124:
        return CliAuthStatus(
            name="codex-cli",
            executable=exe,
            installed=True,
            authenticated=False,
            mode="unknown",
            detail="status check timed out",
        )
    text = (out + "\n" + err).lower()
    authed = rc == 0 and "logged in" in text and "not logged in" not in text
    if not authed:
        return CliAuthStatus(
            name="codex-cli",
            executable=exe,
            installed=True,
            authenticated=False,
            mode=None,
            detail="installed but not authenticated",
        )
    if "chatgpt" in text:
        mode, detail = "subscription", "authenticated via ChatGPT"
    elif "api key" in text or "api-key" in text:
        mode, detail = "api-key", "authenticated via API key"
    else:
        mode, detail = "unknown", "authenticated"
    return CliAuthStatus(
        name="codex-cli",
        executable=exe,
        installed=True,
        authenticated=authed,
        mode=mode,
        detail=detail,
    )


def _try_json(text: str) -> dict[str, object] | None:
    text = text.strip()
    if not text or not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def redact_status_detail(detail: str) -> str:
    """Redaction pass for any status text before it is displayed or stored."""
    return redact(detail)
