"""Secret redaction for all output, logs, and exception messages.

Two layers of defense:

1. **Exact-match registry.** When a real secret is loaded from the keyring at
   runtime, callers register it with :func:`register_secret`. Any later text
   containing that exact value is scrubbed, regardless of shape.
2. **Pattern heuristics.** Well-known credential shapes (API keys, bearer
   tokens, OAuth tokens) are matched by regex as a backstop for values that were
   never registered (e.g. a token echoed inside an upstream error body).

The registry lives only in process memory and is never persisted. The raw
registered values are themselves never emitted — only their redacted form.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "***REDACTED***"

# Minimum length before we treat a registered value as worth scrubbing. Short
# values (e.g. empty strings, "1") would cause pathological over-redaction.
_MIN_SECRET_LEN = 6

_registered_secrets: set[str] = set()

# Ordered (pattern, replacement) heuristics. Each captures a leading label group
# so the reader still sees *which kind* of secret was present.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Anthropic API keys: sk-ant-...
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), f"sk-ant-{REDACTED}"),
    # OpenAI keys: sk-... / sk-proj-...
    (re.compile(r"sk-(proj-)?[A-Za-z0-9_\-]{16,}"), f"sk-{REDACTED}"),
    # Google OAuth access tokens: ya29....
    (re.compile(r"ya29\.[A-Za-z0-9_\-]{10,}"), f"ya29.{REDACTED}"),
    # Google OAuth refresh tokens: 1//....
    (re.compile(r"1//[A-Za-z0-9_\-]{20,}"), f"1//{REDACTED}"),
    # Notion internal integration secrets: secret_... / ntn_...
    (re.compile(r"\b(secret_|ntn_)[A-Za-z0-9]{16,}"), rf"\1{REDACTED}"),
    # Authorization: Bearer <token>
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._\-]+"),
        rf"\1{REDACTED}",
    ),
    # x-api-key / api_key style headers and fields
    (
        re.compile(r"(?i)(x-api-key\s*[:=]\s*)[A-Za-z0-9._\-]+"),
        rf"\1{REDACTED}",
    ),
]


def register_secret(value: str | None) -> None:
    """Register an exact secret value to be scrubbed from all future output."""
    if value and len(value) >= _MIN_SECRET_LEN:
        _registered_secrets.add(value)


def clear_registered_secrets() -> None:
    """Drop all registered secrets. Primarily for test isolation."""
    _registered_secrets.clear()


def redact(text: str) -> str:
    """Return *text* with registered secrets and known credential shapes removed."""
    if not text:
        return text
    # Exact registered values first — longest first so overlapping values collapse
    # to a single marker rather than leaving fragments.
    for secret in sorted(_registered_secrets, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_obj(obj: Any) -> Any:
    """Recursively redact strings inside mappings and sequences for structured logs."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, Mapping):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact_obj(v) for v in obj)
    return obj


class RedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from every formatted log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive; never let logging crash
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
