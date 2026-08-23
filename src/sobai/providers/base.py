"""The common provider interface and shared retry/backoff helpers.

Every provider — HTTP or CLI-bridge — implements :class:`Provider`. The
orchestrator depends only on this abstraction, so adding a provider never
touches connector, CLI, or core code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sobai.core.retry import retry_async
from sobai.core.types import Completion, GenerateParams, ModelInfo, StreamEvent

# Re-exported for backward compatibility; the implementation lives in core.retry.
__all__ = ["Provider", "ProviderHealth", "RetryClass", "retry_async"]


@dataclass(slots=True)
class ProviderHealth:
    """Result of a provider health probe, surfaced by ``sobai doctor``."""

    provider: str
    ok: bool
    detail: str
    models: list[str] = field(default_factory=list)


class RetryClass:
    """Classification of an error for retry purposes."""

    RETRYABLE = "retryable"
    FATAL = "fatal"


class Provider(ABC):
    """Common interface for all model providers."""

    #: Registry name, e.g. "anthropic".
    name: str = "base"
    #: True when the provider runs entirely on the local machine.
    is_local: bool = False

    @abstractmethod
    async def generate(self, params: GenerateParams) -> Completion:
        """Run a single (non-streaming) generation, returning one completion.

        The completion may contain tool-call requests; the orchestrator, not the
        provider, decides whether/how to execute them.
        """

    @abstractmethod
    def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        """Stream a generation as incremental :class:`StreamEvent` values."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Discover available models. Raise ``ProviderError`` if unsupported."""

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Probe reachability/credentials without spending significant tokens."""

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        """Release any held resources (HTTP clients, subprocesses)."""
        return None
