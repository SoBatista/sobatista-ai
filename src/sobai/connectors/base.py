"""The connector contract.

A connector is the counterpart to a provider: it fetches (and later, modifies)
data in an external system. It exposes read-only capabilities as a
:class:`~sobai.tools.ToolRegistry` of typed tools so any provider can drive it
through the orchestrator — without the connector and provider ever importing each
other.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from sobai.core.classification import DataClass
from sobai.tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class ConnectorStatus:
    """Diagnostic snapshot of a connector, for ``sobai doctor`` / ``connections``."""

    name: str
    connected: bool
    detail: str
    account: str | None = None
    scopes: tuple[str, ...] = ()


class Connector(ABC):
    """Common interface for external-data connectors."""

    #: Registry name, e.g. "youtube".
    name: str = "base"
    #: Default classification of data this connector returns.
    default_data_class: DataClass = DataClass.INTERNAL

    @abstractmethod
    def is_connected(self) -> bool:
        """True when credentials/tokens for this connector are present."""

    @abstractmethod
    def status(self) -> ConnectorStatus:
        """Return a diagnostic snapshot (never includes secrets)."""

    @abstractmethod
    def tools(self) -> ToolRegistry:
        """Return the read-only tools this connector exposes to models."""
