"""The orchestration loop: generation plus a bounded tool-call cycle.

Given a provider and (optionally) a tool registry, the orchestrator runs the
model, executes any requested tools it is allowed to run, feeds the results back,
and repeats up to a hard round limit. Write tools are refused unless writes were
explicitly enabled. The loop is provider-agnostic and connector-agnostic — it
only speaks the neutral types in :mod:`sobai.core.types`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from sobai.core.errors import SobaiError, ToolLimitError
from sobai.core.redaction import redact
from sobai.core.types import (
    Completion,
    GenerateParams,
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from sobai.providers.base import Provider
from sobai.storage import Database
from sobai.tools import ToolRegistry


@dataclass(slots=True)
class RunResult:
    text: str
    usage: Usage
    tool_rounds: int
    stop_reason: StopReason


class Orchestrator:
    def __init__(
        self,
        provider: Provider,
        *,
        registry: ToolRegistry | None = None,
        max_tool_rounds: int = 6,
        allow_writes: bool = False,
        db: Database | None = None,
        run_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_tool_rounds = max_tool_rounds
        self.allow_writes = allow_writes
        self._db = db
        self._run_id = run_id

    async def run(
        self,
        params: GenerateParams,
        *,
        stream: bool = False,
        on_text: Callable[[str], None] | None = None,
    ) -> RunResult:
        if self.registry is not None and not params.tools:
            params.tools = self.registry.specs(include_writes=self.allow_writes)

        usage = Usage()
        tool_rounds = 0
        while True:
            if stream:
                completion = await self._stream_collect(params, on_text)
            else:
                completion = await self.provider.generate(params)
            usage = usage.merge(completion.usage)

            if not completion.tool_calls or self.registry is None:
                return RunResult(
                    text=completion.text,
                    usage=usage,
                    tool_rounds=tool_rounds,
                    stop_reason=completion.stop_reason,
                )

            if tool_rounds >= self.max_tool_rounds:
                raise ToolLimitError(
                    f"Exceeded the maximum of {self.max_tool_rounds} tool rounds.",
                    hint="Increase policy.max_tool_rounds or simplify the request.",
                )
            tool_rounds += 1
            await self._append_turn(params, completion, tool_rounds)

    async def _stream_collect(
        self, params: GenerateParams, on_text: Callable[[str], None] | None
    ) -> Completion:
        from sobai.core.types import StreamEventType

        final: Completion | None = None
        async for event in self.provider.stream(params):
            if event.type is StreamEventType.TEXT and on_text is not None:
                on_text(event.text)
            elif event.type is StreamEventType.DONE and event.completion is not None:
                final = event.completion
        return final or Completion(stop_reason=StopReason.END_TURN)

    async def _append_turn(
        self, params: GenerateParams, completion: Completion, round_: int
    ) -> None:
        assistant_blocks: list[TextBlock | ToolUseBlock | ToolResultBlock] = []
        if completion.text:
            assistant_blocks.append(TextBlock(text=completion.text))
        for tc in completion.tool_calls:
            assistant_blocks.append(ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments))
        params.messages.append(Message(role=Role.ASSISTANT, content=assistant_blocks))

        result_blocks: list[TextBlock | ToolUseBlock | ToolResultBlock] = []
        for tc in completion.tool_calls:
            result_blocks.append(await self._execute(tc, round_))
        params.messages.append(Message(role=Role.TOOL, content=result_blocks))

    async def _execute(self, tc: ToolCall, round_: int) -> ToolResultBlock:
        assert self.registry is not None
        tool = self.registry.get(tc.name)
        if tool is None:
            self._record(tc.name, writes=False, status="unknown", round_=round_)
            return ToolResultBlock(
                tool_use_id=tc.id, content=f"Unknown tool: {tc.name}", is_error=True
            )
        if tool.writes and not self.allow_writes:
            self._record(tc.name, writes=True, status="blocked", round_=round_)
            return ToolResultBlock(
                tool_use_id=tc.id,
                content=f"Tool '{tc.name}' would modify data and is disabled. "
                "Re-run with --apply to enable write actions.",
                is_error=True,
            )
        start = time.monotonic()
        try:
            content = await tool.run(tc.arguments)
            status = "ok"
            is_error = False
        except SobaiError as exc:
            content = f"Tool error: {exc.message}"
            status = "error"
            is_error = True
        except Exception as exc:
            content = f"Tool error: {redact(str(exc))}"
            status = "error"
            is_error = True
        duration_ms = int((time.monotonic() - start) * 1000)
        self._record(
            tc.name,
            writes=tool.writes,
            status=status,
            duration_ms=duration_ms,
            round_=round_,
        )
        return ToolResultBlock(tool_use_id=tc.id, content=content, is_error=is_error)

    def _record(
        self,
        name: str,
        *,
        writes: bool,
        status: str,
        round_: int = 0,
        duration_ms: int | None = None,
    ) -> None:
        if self._db is not None and self._run_id is not None:
            self._db.record_tool_call(
                self._run_id,
                round_=round_,
                tool_name=name,
                writes=writes,
                status=status,
                duration_ms=duration_ms,
            )
