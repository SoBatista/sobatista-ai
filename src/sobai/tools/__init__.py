"""Shared tool layer: typed, JSON-Schema tool definitions and a registry.

Tools are the *only* way a model can act on the outside world. Each tool
declares whether it writes (mutates external state) and the data classification
of what it returns, so the orchestrator and policy engine can reason about it.
The same tools are designed to be re-exposed over MCP without change.
"""

from .base import Tool, ToolRegistry

__all__ = ["Tool", "ToolRegistry"]
