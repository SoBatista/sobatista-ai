"""The common provider interface and shared retry/backoff helpers.

Every provider — HTTP or CLI-bridge — implements :class:`Provider`. The
orchestrator depends only on this abstraction, so adding a provider never
touches connector, CLI, or core code.
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from sobai.core.types import Completion, GenerateParams, ModelInfo, StreamEvent


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


async def retry_async[T](
    factory: Callable[[], Awaitable[T]],
    *,
    is_retryable: Callable[[Exception], bool],
    retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> T:
    """Run ``factory`` with bounded exponential backoff on retryable errors.

    ``retries`` is the number of *additional* attempts after the first, so total
    attempts == ``retries + 1``. Non-retryable exceptions propagate immediately.
    """
    attempt = 0
    while True:
        try:
            return await factory()
        except Exception as exc:
            if attempt >= retries or not is_retryable(exc):
                raise
            delay = min(max_delay, base_delay * (2**attempt))
            # Full jitter to avoid synchronized retries.
            delay = random.uniform(0, delay)  # noqa: S311 - jitter, not security
            await asyncio.sleep(delay)
            attempt += 1
