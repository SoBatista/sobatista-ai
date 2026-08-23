"""OpenAI provider — the Responses API with native function/tool calling.

Wire contract (verified against the current OpenAI Responses API):

* ``POST /v1/responses`` with ``Authorization: Bearer`` header
* ``instructions`` carries the system prompt; ``input`` is a list of items
* function tools are flat: ``{type:"function", name, description, parameters}``
* the model requests a tool via an ``output`` item ``{type:"function_call",
  call_id, name, arguments}``; results are fed back as ``{type:
  "function_call_output", call_id, output}`` input items
* streaming is SSE; ``response.output_text.delta`` carries text, and
  ``response.completed`` carries the final response object
* model discovery: ``GET /v1/models``
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


def _to_input(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert messages into (instructions, input-items) for the Responses API."""
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.role.value if isinstance(msg.role, Role) else msg.role
        if role == Role.SYSTEM.value:
            instructions.append(msg.text())
            continue
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block.id,
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    }
                )
            elif isinstance(block, ToolResultBlock):
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block.tool_use_id,
                        "output": block.content,
                    }
                )
            else:  # TextBlock
                content_type = "output_text" if role == Role.ASSISTANT.value else "input_text"
                items.append(
                    {
                        "role": role,
                        "content": [{"type": content_type, "text": block.text}],
                    }
                )
    system = "\n\n".join(p for p in instructions if p) or None
    return system, items


class OpenAIProvider(HttpProvider):
    name = "openai"
    is_local = False

    def __init__(self, *, api_key: str, base_url: str, timeout_s: float = 120.0) -> None:
        super().__init__(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            timeout_s=timeout_s,
        )

    def _build_payload(self, params: GenerateParams, *, stream: bool) -> dict[str, Any]:
        instructions, items = _to_input(params.messages)
        payload: dict[str, Any] = {
            "model": params.model,
            "input": items,
            "max_output_tokens": params.max_tokens,
            "stream": stream,
        }
        if instructions:
            payload["instructions"] = instructions
        if params.temperature is not None:
            payload["temperature"] = params.temperature
        if params.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                }
                for t in params.tools
            ]
        if params.response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "sobai_structured_output",
                    "schema": params.response_schema,
                    "strict": True,
                }
            }
        return payload

    def _parse_response(self, data: dict[str, Any]) -> Completion:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        refusal = False
        for item in data.get("output", []):
            itype = item.get("type")
            if itype == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "refusal":
                        refusal = True
                        text_parts.append(part.get("refusal", ""))
            elif itype == "function_call":
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=item.get("call_id", item.get("id", "")),
                        name=item["name"],
                        arguments=args,
                    )
                )
        usage_raw = data.get("usage", {})
        if refusal:
            stop = StopReason.REFUSAL
        elif tool_calls:
            stop = StopReason.TOOL_USE
        elif data.get("status") == "incomplete" and (
            data.get("incomplete_details", {}).get("reason") == "max_output_tokens"
        ):
            stop = StopReason.MAX_TOKENS
        else:
            stop = StopReason.END_TURN
        return Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop,
            usage=Usage(
                input_tokens=usage_raw.get("input_tokens"),
                output_tokens=usage_raw.get("output_tokens"),
            ),
            model=data.get("model"),
        )

    async def generate(self, params: GenerateParams) -> Completion:
        payload = self._build_payload(params, stream=False)

        async def _call() -> httpx.Response:
            return await self._post("/responses", payload, timeout_s=params.timeout_s)

        resp = await retry_async(_call, is_retryable=is_retryable_http, retries=self._retries)
        return self._parse_response(resp.json())

    async def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]:
        payload = self._build_payload(params, stream=True)
        completion: Completion | None = None
        try:
            async with self._client.stream(
                "POST", "/responses", json=payload, timeout=params.timeout_s
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    event = json.loads(raw)
                    etype = event.get("type", "")
                    if etype == "response.output_text.delta":
                        yield StreamEvent(type=StreamEventType.TEXT, text=event.get("delta", ""))
                    elif etype == "response.completed":
                        completion = self._parse_response(event.get("response", {}))
                    elif etype in ("response.failed", "error", "response.error"):
                        detail = json.dumps(event)[:400]
                        raise ProviderError(f"{self.name}: streaming error: {detail}")
        except httpx.HTTPStatusError as exc:
            raise self._wrap_status_error(exc) from exc
        except httpx.TransportError as exc:
            raise self._wrap_transport_error(exc) from exc
        yield StreamEvent(
            type=StreamEventType.DONE, completion=completion or Completion(model=params.model)
        )

    async def list_models(self) -> list[ModelInfo]:
        resp = await self._get("/models")
        data = resp.json()
        return [ModelInfo(id=m["id"], provider=self.name) for m in data.get("data", [])]

    async def health(self) -> ProviderHealth:
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return ProviderHealth(provider=self.name, ok=False, detail=exc.message)
        return ProviderHealth(
            provider=self.name,
            ok=True,
            detail="reachable; credentials valid",
            models=[m.id for m in models[:5]],
        )
