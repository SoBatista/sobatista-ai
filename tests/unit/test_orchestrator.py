from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from sobai.core.errors import ToolLimitError
from sobai.core.orchestrator import Orchestrator
from sobai.core.types import (
    Completion,
    GenerateParams,
    Message,
    StopReason,
    StreamEvent,
    StreamEventType,
    ToolCall,
)
from sobai.providers.base import Provider, ProviderHealth
from sobai.tools import Tool, ToolRegistry


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, completions: list[Completion], *, loop_last: bool = False) -> None:
        self._completions = completions
        self._loop_last = loop_last
        self.calls = 0

    async def generate(self, params: GenerateParams) -> Completion:
        idx = min(self.calls, len(self._completions) - 1) if self._loop_last else self.calls
        self.calls += 1
        return self._completions[idx]

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        completion = await self.generate(params)
        if completion.text:
            yield StreamEvent(type=StreamEventType.TEXT, text=completion.text)
        yield StreamEvent(type=StreamEventType.DONE, completion=completion)

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


class EchoTool(Tool):
    name = "echo"
    description = "Echo the input"
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    async def run(self, arguments: dict[str, Any]) -> str:
        return f"echoed:{arguments.get('x')}"


class WriteTool(Tool):
    name = "danger"
    description = "Would modify data"
    writes = True

    def __init__(self) -> None:
        self.executed = False

    async def run(self, arguments: dict[str, Any]) -> str:
        self.executed = True
        return "wrote"


async def test_plain_completion_no_tools() -> None:
    provider = ScriptedProvider([Completion(text="hello", stop_reason=StopReason.END_TURN)])
    orch = Orchestrator(provider, registry=None)
    result = await orch.run(GenerateParams(model="m", messages=[Message.user("hi")]))
    assert result.text == "hello"
    assert result.tool_rounds == 0


async def test_tool_loop_executes_and_finishes() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[ToolCall(id="t1", name="echo", arguments={"x": "hi"})],
                stop_reason=StopReason.TOOL_USE,
            ),
            Completion(text="done", stop_reason=StopReason.END_TURN),
        ]
    )
    orch = Orchestrator(provider, registry=reg, max_tool_rounds=5)
    result = await orch.run(GenerateParams(model="m", messages=[Message.user("go")]))
    assert result.text == "done"
    assert result.tool_rounds == 1


async def test_write_tool_blocked_without_apply() -> None:
    tool = WriteTool()
    reg = ToolRegistry()
    reg.register(tool)
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[ToolCall(id="t1", name="danger", arguments={})],
                stop_reason=StopReason.TOOL_USE,
            ),
            Completion(text="ok", stop_reason=StopReason.END_TURN),
        ]
    )
    orch = Orchestrator(provider, registry=reg, allow_writes=False)
    await orch.run(GenerateParams(model="m", messages=[Message.user("go")]))
    assert tool.executed is False  # never ran


async def test_write_tool_runs_with_apply() -> None:
    tool = WriteTool()
    reg = ToolRegistry()
    reg.register(tool)
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[ToolCall(id="t1", name="danger", arguments={})],
                stop_reason=StopReason.TOOL_USE,
            ),
            Completion(text="ok", stop_reason=StopReason.END_TURN),
        ]
    )
    orch = Orchestrator(provider, registry=reg, allow_writes=True)
    await orch.run(GenerateParams(model="m", messages=[Message.user("go")]))
    assert tool.executed is True


async def test_read_only_specs_exclude_writes() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(WriteTool())
    assert {s.name for s in reg.specs(include_writes=False)} == {"echo"}
    assert {s.name for s in reg.specs(include_writes=True)} == {"echo", "danger"}


async def test_tool_round_limit_enforced() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    always = Completion(
        tool_calls=[ToolCall(id="t", name="echo", arguments={})],
        stop_reason=StopReason.TOOL_USE,
    )
    provider = ScriptedProvider([always], loop_last=True)
    orch = Orchestrator(provider, registry=reg, max_tool_rounds=2)
    with pytest.raises(ToolLimitError):
        await orch.run(GenerateParams(model="m", messages=[Message.user("go")]))
