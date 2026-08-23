"""Provider adapters: models that reason and request tool calls.

Providers implement a single common interface (:class:`~sobai.providers.base.Provider`).
They are never coupled to connectors — a provider knows how to talk to a model,
nothing more.
"""

from .base import Provider, ProviderHealth

__all__ = ["Provider", "ProviderHealth"]
