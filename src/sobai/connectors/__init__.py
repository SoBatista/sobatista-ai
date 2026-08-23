"""Connector adapters: external systems that retrieve or modify data.

Connectors are strictly separate from providers. A connector knows how to talk to
an external system (YouTube, Notion, …) and exposes its capabilities as typed,
JSON-Schema tools. It never imports a provider, and the data it returns is always
treated as untrusted.
"""

from .base import Connector, ConnectorStatus

__all__ = ["Connector", "ConnectorStatus"]
