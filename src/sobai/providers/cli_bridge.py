"""Optional bridges to locally installed AI CLIs (Claude Code, Codex).

These providers relay a prompt to an installed CLI and capture its output. They
are a distinct authentication mode: they use the CLI's *own* installed login (a
Claude Code / ChatGPT subscription), never SoBatista AI's API credentials, and
never assume a subscription is an API key.

Safety properties:

* prompts are passed as **subprocess argv elements** — never through a shell, so
  there is no shell interpolation or injection surface
* a missing executable raises :class:`ProviderUnavailableError` cleanly
* every invocation has a timeout and is cancellable; on timeout the process is
  killed
* failures never silently fall back to a different provider

Because these bridges relay to cloud backends, they are **not** local providers
and are blocked under ``--local-only``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator

from sobai.core.errors import OperationTimeout, ProviderError, ProviderUnavailableError
from sobai.core.redaction import redact
from sobai.core.types import (
    Completion,
    GenerateParams,
    ModelInfo,
    StopReason,
    StreamEvent,
    StreamEventType,
    Usage,
)

from .base import Provider, ProviderHealth


class CliBridgeProvider(Provider):
    """Base class for subprocess-backed provider bridges."""

    is_local = False
    #: Executable name to look up on PATH.
    executable: str = ""

    def __init__(self, *, timeout_s: float = 120.0) -> None:
        self._timeout = timeout_s

    # -- to be provided by subclasses -------------------------------------
    def _build_argv(self, params: GenerateParams, prompt: str) -> list[str]:
        raise NotImplementedError

    def _extract_text(self, stdout: str) -> str:
        return stdout.strip()

    # -- helpers -----------------------------------------------------------
    def _resolve_exe(self) -> str:
        path = shutil.which(self.executable)
        if not path:
            raise ProviderUnavailableError(
                f"{self.name}: '{self.executable}' is not installed or not on PATH.",
                hint=f"Install the {self.executable} CLI and authenticate it, "
                "or choose another provider. This bridge uses the CLI's own login, "
                "not an API key.",
            )
        return path

    def _prompt_from(self, params: GenerateParams) -> str:
        # Flatten the conversation into a single prompt string. System messages
        # are prepended so a bridge that lacks a system channel still receives them.
        parts: list[str] = []
        for msg in params.messages:
            role = msg.role.value if hasattr(msg.role, "value") else msg.role
            text = msg.text()
            if not text:
                continue
            parts.append(text if role == "user" else f"[{role}]\n{text}")
        return "\n\n".join(parts)

    async def generate(self, params: GenerateParams) -> Completion:
        exe = self._resolve_exe()
        prompt = self._prompt_from(params)
        argv = [exe, *self._build_argv(params, prompt)[1:]]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=params.timeout_s)
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
        return Completion(
            text=self._extract_text(stdout),
            stop_reason=StopReason.END_TURN,
            usage=Usage(),
            model=params.model or self.name,
        )

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        # CLI bridges return a whole response; surface it as a single chunk so the
        # streaming interface still works uniformly.
        completion = await self.generate(params)
        if completion.text:
            yield StreamEvent(type=StreamEventType.TEXT, text=completion.text)
        yield StreamEvent(type=StreamEventType.DONE, completion=completion)

    async def list_models(self) -> list[ModelInfo]:
        # Bridges delegate model selection to the underlying CLI's own config.
        raise ProviderError(
            f"{self.name}: model discovery is not supported for CLI bridges.",
            hint="Model selection is delegated to the underlying CLI.",
        )

    async def health(self) -> ProviderHealth:
        path = shutil.which(self.executable)
        if not path:
            return ProviderHealth(
                provider=self.name,
                ok=False,
                detail=f"'{self.executable}' not found on PATH (bridge is optional).",
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except (TimeoutError, OSError) as exc:  # pragma: no cover
            return ProviderHealth(provider=self.name, ok=False, detail=str(exc))
        version = out_b.decode("utf-8", "replace").strip().splitlines()[:1]
        return ProviderHealth(
            provider=self.name,
            ok=True,
            detail=f"installed: {version[0] if version else path}",
        )


class ClaudeCliProvider(CliBridgeProvider):
    """Bridge to the installed Claude Code CLI (``claude``) in headless print mode."""

    name = "claude-cli"
    executable = "claude"

    def _build_argv(self, params: GenerateParams, prompt: str) -> list[str]:
        argv = [self.executable, "--print", "--output-format", "json"]
        if params.model:
            argv += ["--model", params.model]
        argv.append(prompt)
        return argv

    def _extract_text(self, stdout: str) -> str:
        # `--output-format json` yields an object with a `result` field; fall back
        # to raw stdout if the format differs across CLI versions.
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout.strip()
        if isinstance(data, dict):
            for key in ("result", "response", "text", "content"):
                value = data.get(key)
                if isinstance(value, str):
                    return value.strip()
        return stdout.strip()


class CodexCliProvider(CliBridgeProvider):
    """Bridge to the installed Codex CLI (``codex``) in non-interactive exec mode."""

    name = "codex-cli"
    executable = "codex"

    def _build_argv(self, params: GenerateParams, prompt: str) -> list[str]:
        argv = [self.executable, "exec"]
        if params.model:
            argv += ["--model", params.model]
        argv.append(prompt)
        return argv
