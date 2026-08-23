"""Exception hierarchy and process exit codes.

Every user-facing failure in SoBatista AI raises a :class:`SobaiError` subclass.
The CLI top level catches these, renders an actionable message (with secrets
redacted), and exits with the class's :attr:`~SobaiError.exit_code`. This keeps
exit semantics predictable for scripting and CI.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable process exit codes. Do not renumber existing values."""

    OK = 0
    GENERAL = 1
    USAGE = 2
    CONFIG = 3
    AUTH = 4
    PROVIDER = 5
    CONNECTOR = 6
    POLICY = 7
    TOOL_LIMIT = 8
    NOT_FOUND = 9
    TIMEOUT = 10
    DEPENDENCY = 11
    BUILD = 12
    UPDATE = 13
    CANCELLED = 130


class SobaiError(Exception):
    """Base class for all expected, user-facing errors.

    Attributes:
        exit_code: Process exit code the CLI should use.
        hint: Optional actionable next step shown to the user.
    """

    exit_code: ExitCode = ExitCode.GENERAL

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigError(SobaiError):
    exit_code = ExitCode.CONFIG


class AuthError(SobaiError):
    """Credential missing, invalid, or keyring unavailable."""

    exit_code = ExitCode.AUTH


class ProviderError(SobaiError):
    """A model provider failed or is misconfigured."""

    exit_code = ExitCode.PROVIDER


class ProviderUnavailableError(ProviderError):
    """A provider (or its backing CLI/daemon) is not installed or reachable."""


class ConnectorError(SobaiError):
    """An external connector (YouTube, Notion, ...) failed or is misconfigured."""

    exit_code = ExitCode.CONNECTOR


class PolicyError(SobaiError):
    """A policy (local-only, egress consent, allowlist) blocked the operation."""

    exit_code = ExitCode.POLICY


class LocalOnlyViolation(PolicyError):
    """An operation would have sent data to an external API under ``--local-only``."""


class ToolLimitError(SobaiError):
    """The per-run tool-call round budget was exhausted."""

    exit_code = ExitCode.TOOL_LIMIT


class NotFoundError(SobaiError):
    exit_code = ExitCode.NOT_FOUND


class OperationTimeout(SobaiError):
    """An operation exceeded its timeout budget."""

    exit_code = ExitCode.TIMEOUT


class DependencyError(SobaiError):
    """A required external tool (e.g. ``uv``) is unavailable."""

    exit_code = ExitCode.DEPENDENCY


class BuildError(SobaiError):
    """Building/validating a source checkout failed."""

    exit_code = ExitCode.BUILD


class UpdateError(SobaiError):
    """Installing or verifying the refreshed tool failed."""

    exit_code = ExitCode.UPDATE


class OperationDeclined(SobaiError):
    """The user declined a confirmation prompt."""

    exit_code = ExitCode.CANCELLED
