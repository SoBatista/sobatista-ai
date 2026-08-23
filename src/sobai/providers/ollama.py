"""Ollama provider — local model runtime via the Ollama HTTP API.

Wire contract (verified against the current Ollama API):

* ``POST /api/chat`` with ``{model, messages, stream, tools?, options?}``
* messages use roles ``system|user|assistant|tool``; assistant tool requests are
  ``message.tool_calls`` with ``{function:{name, arguments}}`` (arguments is a
  JSON object, not a string)
* streaming is newline-delimited JSON (one object per line)
* token counts: ``prompt_eval_count`` / ``eval_count``
* model discovery: ``GET /api/tags``

This provider is *local*: :attr:`is_local` is True, so it is permitted under
``--local-only`` and never triggers a cloud-egress prompt.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from sobai.core.errors import ProviderError
from sobai.core.types import (
    Completion,
    GenerateParams,
    Message,
    ModelInfo,
    Role,
    StopReason,
    StreamEvent,
    StreamEventType,
    ToolCall,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

from .base import ProviderHealth, retry_async
from .http import HttpProvider, is_retryable_http


def _to_ollama(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate neutral messages into Ollama's chat message list.

    Tool results become standalone ``role: "tool"`` messages (Ollama's format);
    an assistant tool request becomes ``message.tool_calls``. A message that
    carried *only* tool results contributes no extra speaker entry.
    """
    id_to_name: dict[str, str] = {}
    wire: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.role.value if isinstance(msg.role, Role) else msg.role
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                id_to_name[block.id] = block.name
                tool_calls.append({"function": {"name": block.name, "arguments": block.input}})
            elif isinstance(block, ToolResultBlock):
                tool_results.append(
                    {
                        "role": "tool",
                        "content": block.content,
                        "tool_name": id_to_name.get(block.tool_use_id, ""),
                    }
                )
            else:
                text_parts.append(block.text)
        wire.extend(tool_results)
        if text_parts or tool_calls or not tool_results:
            entry: dict[str, Any] = {"role": role, "content": "".join(text_parts)}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            wire.append(entry)
    return wire


class OllamaProvider(HttpProvider):
    name = "ollama"
    is_local = True

    def __init__(self, *, base_url: str, timeout_s: float = 120.0) -> None:
        super().__init__(base_url=base_url, timeout_s=timeout_s)

    def _build_payload(self, params: GenerateParams, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": params.model,
            "messages": _to_ollama(params.messages),
            "stream": stream,
        }
        options: dict[str, Any] = {"num_predict": params.max_tokens}
        if params.temperature is not None:
            options["temperature"] = params.temperature
        payload["options"] = options
        if params.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in params.tools
            ]
        return payload

    def _parse_tool_calls(self, message: dict[str, Any]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for i, tc in enumerate(message.get("tool_calls", []) or []):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(id=f"call_{i}", name=fn.get("name", ""), arguments=args))
        return calls

    async def generate(self, params: GenerateParams) -> Completion:
        payload = self._build_payload(params, stream=False)

        async def _call() -> httpx.Response:
            return await self._post("/api/chat", payload, timeout_s=params.timeout_s)

        resp = await retry_async(_call, is_retryable=is_retryable_http, retries=self._retries)
        data = resp.json()
        message = data.get("message", {})
        tool_calls = self._parse_tool_calls(message)
        return Completion(
            text=message.get("content", ""),
            tool_calls=tool_calls,
            stop_reason=StopReason.TOOL_USE if tool_calls else StopReason.END_TURN,
            usage=Usage(
                input_tokens=data.get("prompt_eval_count"),
                output_tokens=data.get("eval_count"),
            ),
            model=data.get("model", params.model),
        )

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        payload = self._build_payload(params, stream=True)
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = Usage()
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=payload, timeout=params.timeout_s
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    chunk = json.loads(line)
                    message = chunk.get("message", {})
                    content = message.get("content", "")
                    if content:
                        text_parts.append(content)
                        yield StreamEvent(type=StreamEventType.TEXT, text=content)
                    if message.get("tool_calls"):
                        tool_calls = self._parse_tool_calls(message)
                    if chunk.get("done"):
                        usage = Usage(
                            input_tokens=chunk.get("prompt_eval_count"),
                            output_tokens=chunk.get("eval_count"),
                        )
        except httpx.HTTPStatusError as exc:
            raise self._wrap_status_error(exc) from exc
        except httpx.TransportError as exc:
            raise self._wrap_transport_error(exc) from exc
        yield StreamEvent(
            type=StreamEventType.DONE,
            completion=Completion(
                text="".join(text_parts),
                tool_calls=tool_calls,
                stop_reason=StopReason.TOOL_USE if tool_calls else StopReason.END_TURN,
                usage=usage,
                model=params.model,
            ),
        )

    async def list_models(self) -> list[ModelInfo]:
        resp = await self._get("/api/tags")
        data = resp.json()
        return [
            ModelInfo(id=m["name"], provider=self.name, display_name=m.get("name"))
            for m in data.get("models", [])
        ]

    async def health(self) -> ProviderHealth:
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return ProviderHealth(
                provider=self.name,
                ok=False,
                detail=exc.message,
            )
        return ProviderHealth(
            provider=self.name,
            ok=True,
            detail=f"reachable; {len(models)} model(s) installed",
            models=[m.id for m in models[:8]],
        )
