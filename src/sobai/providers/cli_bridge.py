"""Hardened bridges to locally installed AI CLIs (Claude Code, Codex).

These providers relay a prompt to an installed CLI and capture its output. They
are a distinct authentication mode: they use the CLI's *own* installed login (a
Claude Code / ChatGPT subscription), never SoBatista AI's API credentials, and
never assume a subscription is an API key. They never silently fall back to a
different provider or to an API.

Security properties (enforced, and feature-detected against the installed CLI):

* the prompt is delivered over **stdin**, never as an argv element, so it does
  not appear in the process list and there is no shell interpolation
* subprocesses are spawned with argv arrays (never a shell), a timeout, and are
  cancellable; on timeout the process is killed
* built-in tools, MCP servers, hooks, plugins, slash commands, session
  persistence, and project/local settings are disabled for ordinary ``ask``
* the CLI runs from an application-controlled empty working directory so
  repository content (CLAUDE.md, .rules, .mcp.json, hooks) is never loaded
* API-key environment variables are stripped so the CLI uses its subscription
  login, never metered API billing
* if a required security flag is not supported by the installed CLI, the bridge
  **fails closed** rather than running without the boundary

Because these bridges relay to cloud backends, they are **not** local providers
and are blocked under ``--local-only``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from sobai.core.errors import OperationTimeout, ProviderError, ProviderUnavailableError
from sobai.core.redaction import redact
from sobai.core.types import (
    Completion,
    GenerateParams,
    ModelInfo,
    Role,
    StreamEvent,
    StreamEventType,
    Usage,
)

from . import cli_status
from .base import Provider, ProviderHealth

# Sentinel model id meaning "let the installed CLI select its configured default".
# Documented internal value; never passed to the CLI as `--model default`.
CLI_DEFAULT_MODEL = "default"

_FLAG_RE = re.compile(r"(--[a-zA-Z0-9][a-zA-Z0-9-]+)")


def _is_default_model(model: str | None) -> bool:
    return not model or model == CLI_DEFAULT_MODEL


class CliBridgeProvider(Provider):
    """Base class for subprocess-backed provider bridges."""

    is_local = False
    executable: str = ""
    #: argv used (plus ``--help``) to discover supported flags.
    help_argv: tuple[str, ...] = ()
    #: flags that MUST be supported or the bridge fails closed.
    required_flags: tuple[str, ...] = ()
    #: environment variables removed so the CLI uses its subscription login.
    strip_env: tuple[str, ...] = ()

    def __init__(self, *, timeout_s: float = 120.0) -> None:
        self._timeout = timeout_s
        self._flags_cache: set[str] | None = None

    # -- discovery / environment ------------------------------------------
    def _resolve_exe(self) -> str:
        path = shutil.which(self.executable)
        if not path:
            raise ProviderUnavailableError(
                f"{self.name}: '{self.executable}' is not installed or not on PATH.",
                hint=f"Install the {self.executable} CLI and authenticate it, or choose "
                "another provider. This bridge uses the CLI's own login, not an API key.",
            )
        return path

    def _run_help(self, exe: str) -> str:
        """Return `--help` text for flag feature-detection (sync; test seam)."""
        try:
            proc = subprocess.run(  # noqa: S603 - argv array, no shell
                [exe, *self.help_argv, "--help"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):  # pragma: no cover
            return ""
        return (proc.stdout or "") + "\n" + (proc.stderr or "")

    def supported_flags(self, exe: str) -> set[str]:
        if self._flags_cache is None:
            self._flags_cache = set(_FLAG_RE.findall(self._run_help(exe)))
        return self._flags_cache

    def _require_flags(self, flags: set[str]) -> None:
        missing = [f for f in self.required_flags if f not in flags]
        if missing:
            raise ProviderError(
                f"{self.name}: the installed CLI does not support required security "
                f"flag(s): {', '.join(missing)}.",
                hint="Update the CLI. SoBatista AI refuses to run the bridge without these "
                "boundaries (fail-closed).",
            )

    def _bridge_env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in self.strip_env:
            env.pop(key, None)
        return env

    # -- message flattening -----------------------------------------------
    @staticmethod
    def _system_text(params: GenerateParams) -> str | None:
        parts: list[str] = [params.system] if params.system else []
        parts += [
            m.text()
            for m in params.messages
            if (m.role.value if isinstance(m.role, Role) else m.role) == Role.SYSTEM.value
            and m.text()
        ]
        return "\n\n".join(parts) or None

    @staticmethod
    def _prompt_text(params: GenerateParams) -> str:
        out: list[str] = []
        for m in params.messages:
            role = m.role.value if isinstance(m.role, Role) else m.role
            if role == Role.SYSTEM.value:
                continue
            text = m.text()
            if text:
                out.append(text if role == Role.USER.value else f"[{role}]\n{text}")
        return "\n\n".join(out)

    # -- subclass hooks ----------------------------------------------------
    def _build_argv(self, exe: str, params: GenerateParams, flags: set[str], cwd: str) -> list[str]:
        raise NotImplementedError

    def _parse_output(self, stdout: str, *, cwd: str, params: GenerateParams) -> Completion:
        raise NotImplementedError

    # -- execution ---------------------------------------------------------
    async def generate(self, params: GenerateParams) -> Completion:
        exe = self._resolve_exe()
        flags = self.supported_flags(exe)
        self._require_flags(flags)
        stdin_text = self._stdin_text(params)
        with tempfile.TemporaryDirectory(prefix="sobai-bridge-") as cwd:
            argv = self._build_argv(exe, params, flags, cwd)
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=self._bridge_env(),
            )
            try:
                out_b, err_b = await asyncio.wait_for(
                    proc.communicate(input=stdin_text.encode()), timeout=params.timeout_s
                )
            except TimeoutError as exc:
                proc.kill()
                await proc.wait()
                raise OperationTimeout(
                    f"{self.name}: '{self.executable}' timed out after {params.timeout_s}s."
                ) from exc
            except asyncio.CancelledError:
                proc.kill()
                await proc.wait()
                raise
            stdout = out_b.decode("utf-8", "replace")
            stderr = err_b.decode("utf-8", "replace")
            if proc.returncode != 0:
                raise ProviderError(
                    f"{self.name}: '{self.executable}' exited with code {proc.returncode}.",
                    hint=redact(stderr.strip())[:400] or "See the CLI's own logs.",
                )
            return self._parse_output(stdout, cwd=cwd, params=params)

    def _stdin_text(self, params: GenerateParams) -> str:
        """Text delivered over stdin. Subclasses may fold the system prompt in."""
        return self._prompt_text(params)

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        completion = await self.generate(params)
        if completion.text:
            yield StreamEvent(type=StreamEventType.TEXT, text=completion.text)
        yield StreamEvent(type=StreamEventType.DONE, completion=completion)

    async def list_models(self) -> list[ModelInfo]:
        raise ProviderError(
            f"{self.name}: model discovery is not supported for CLI bridges.",
            hint="Model selection is delegated to the underlying CLI.",
        )

    async def health(self) -> ProviderHealth:
        status = self._detect()
        if not status.installed:
            return ProviderHealth(
                provider=self.name,
                ok=False,
                detail=f"'{self.executable}' not found on PATH (bridge is optional).",
            )
        return ProviderHealth(
            provider=self.name,
            ok=status.authenticated,
            detail=redact(status.detail),
        )

    def _detect(self) -> cli_status.CliAuthStatus:  # pragma: no cover - overridden
        raise NotImplementedError


class ClaudeCliProvider(CliBridgeProvider):
    """Bridge to the installed Claude Code CLI (``claude``) in hardened print mode."""

    name = "claude-cli"
    executable = "claude"
    help_argv = ()
    required_flags = (
        "--print",
        "--output-format",
        "--tools",
        "--strict-mcp-config",
        "--mcp-config",
    )
    strip_env = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    def _detect(self) -> cli_status.CliAuthStatus:
        return cli_status.detect_claude_cli()

    def _build_argv(self, exe: str, params: GenerateParams, flags: set[str], cwd: str) -> list[str]:
        argv = [
            exe,
            "--print",
            "--output-format",
            "json",
            # Disable ALL built-in tools.
            "--tools",
            "",
            # Only MCP servers from our (empty) config; ignore all others.
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
        ]
        # Defense-in-depth, only when supported by the installed CLI.
        if "--safe-mode" in flags:
            argv.append("--safe-mode")  # no CLAUDE.md/hooks/plugins/MCP/custom commands
        if "--disable-slash-commands" in flags:
            argv.append("--disable-slash-commands")
        if "--no-session-persistence" in flags:
            argv.append("--no-session-persistence")
        if "--setting-sources" in flags:
            argv += ["--setting-sources", ""]  # load no user/project/local settings
        system = self._system_text(params)
        if system and "--append-system-prompt" in flags:
            argv += ["--append-system-prompt", system]
        if not _is_default_model(params.model) and "--model" in flags:
            argv += ["--model", params.model]
        return argv

    def _parse_output(self, stdout: str, *, cwd: str, params: GenerateParams) -> Completion:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return Completion(text=stdout.strip(), model=params.model or self.name)
        if isinstance(data, dict) and data.get("is_error"):
            raise ProviderError(
                f"{self.name}: run reported an error.",
                hint=redact(str(data.get("result") or data.get("subtype") or ""))[:400],
            )
        text = ""
        usage = Usage()
        if isinstance(data, dict):
            for key in ("result", "response", "text"):
                value = data.get(key)
                if isinstance(value, str):
                    text = value.strip()
                    break
            raw = data.get("usage") or {}
            usage = Usage(
                input_tokens=raw.get("input_tokens"),
                output_tokens=raw.get("output_tokens"),
                cached_input_tokens=raw.get("cache_read_input_tokens"),
                # total_cost_usd is a client-side, API-equivalent estimate — never a
                # subscription charge (see docs/subscriptions.md).
                cost_usd=data.get("total_cost_usd"),
            )
        return Completion(text=text, usage=usage, model=params.model or self.name)


class CodexCliProvider(CliBridgeProvider):
    """Bridge to the installed Codex CLI (``codex``) in hardened read-only exec mode."""

    name = "codex-cli"
    executable = "codex"
    help_argv = ("exec",)
    required_flags = ("--json", "--sandbox", "--ephemeral", "--skip-git-repo-check")
    strip_env = ("OPENAI_API_KEY", "CODEX_API_KEY")

    def _detect(self) -> cli_status.CliAuthStatus:
        return cli_status.detect_codex_cli()

    def _last_message_path(self, cwd: str) -> str:
        return str(Path(cwd) / "last_message.txt")

    def _build_argv(self, exe: str, params: GenerateParams, flags: set[str], cwd: str) -> list[str]:
        argv = [
            exe,
            "exec",
            "--json",
            "--sandbox",
            "read-only",  # never workspace-write or danger-full-access
            "--ephemeral",  # no session files persisted
            "--skip-git-repo-check",
        ]
        if "--cd" in flags:
            argv += ["--cd", cwd]
        if "--ignore-user-config" in flags:
            argv.append("--ignore-user-config")  # do not load ~/.codex/config.toml
        if "--ignore-rules" in flags:
            argv.append("--ignore-rules")  # do not load user/project execpolicy rules
        if "--config" in flags or "-c" in flags:
            # Explicitly disable web search and MCP servers.
            argv += ["-c", "tools.web_search=false", "-c", "mcp_servers={}"]
        if "--output-last-message" in flags:
            argv += ["--output-last-message", self._last_message_path(cwd)]
        if not _is_default_model(params.model) and ("--model" in flags or "-m" in flags):
            argv += ["--model", params.model]
        # Read the prompt from stdin via the supported '-' form.
        argv.append("-")
        return argv

    def _stdin_text(self, params: GenerateParams) -> str:
        system = self._system_text(params)
        prompt = self._prompt_text(params)
        return f"[system]\n{system}\n\n{prompt}" if system else prompt

    def _parse_output(self, stdout: str, *, cwd: str, params: GenerateParams) -> Completion:
        text = ""
        last_path = Path(self._last_message_path(cwd))
        if last_path.is_file():
            text = last_path.read_text(encoding="utf-8", errors="replace").strip()
        usage = Usage()
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type", "")
            if etype == "turn.completed":
                raw = event.get("usage", {}) or {}
                usage = Usage(
                    input_tokens=raw.get("input_tokens"),
                    output_tokens=raw.get("output_tokens"),
                    cached_input_tokens=raw.get("cached_input_tokens"),
                    reasoning_tokens=raw.get("reasoning_output_tokens"),
                )
            elif not text and etype in ("item.completed", "item.updated"):
                item = event.get("item", {})
                if item.get("type") in ("agent_message", "assistant_message"):
                    candidate = item.get("text") or item.get("message") or ""
                    if candidate:
                        text = candidate.strip()
        return Completion(text=text, usage=usage, model=params.model or self.name)
