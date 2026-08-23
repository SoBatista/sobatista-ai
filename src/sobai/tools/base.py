"""Tool abstraction and registry.

A :class:`Tool` binds a JSON-Schema contract to an async implementation. Tools
carry two safety-relevant attributes:

* ``writes`` — whether executing the tool mutates external state. Write tools are
  never exposed unless the caller opted in with ``--apply`` (Phase 3+).
* ``data_class`` — the classification of data the tool returns, used by the
  egress policy engine before results are sent to a cloud model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from sobai.core.classification import DataClass
from sobai.core.types import ToolSpec


class Tool(ABC):
    name: str = ""
    description: str = ""
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    writes: bool = False
    data_class: DataClass = DataClass.INTERNAL

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            writes=self.writes,
        )

    @abstractmethod
    async def run(self, arguments: dict[str, Any]) -> str:
        """Execute the tool and return a string result for the model."""


class ToolRegistry:
    """An explicit allowlist of tools available for a given run."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, *, include_writes: bool = False) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values() if include_writes or not t.writes]

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Any:
        return iter(self._tools.values())
