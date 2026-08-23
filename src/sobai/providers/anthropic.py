"""Anthropic provider — direct Messages API with native tool use.

Wire contract (verified against the current Anthropic API):

* ``POST /v1/messages`` with headers ``x-api-key`` and ``anthropic-version``
* ``system`` is a top-level string; ``messages`` are user/assistant turns whose
  content is a list of blocks (``text`` / ``tool_use`` / ``tool_result``)
* tool definitions: ``{name, description, input_schema}``
* streaming is SSE; text arrives as ``content_block_delta`` → ``text_delta``
* model discovery: ``GET /v1/models``

We speak the API over raw HTTPX (see ADR-0002) to keep the provider interface
uniform and dependencies minimal.
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
    ToolCall,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

from .base import ProviderHealth, retry_async
from .http import HttpProvider, is_retryable_http

ANTHROPIC_VERSION = "2023-06-01"

_STOP_MAP = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "refusal": StopReason.REFUSAL,
}


def _content_to_wire(message: Message) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, ToolUseBlock):
            blocks.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
            )
        elif isinstance(block, ToolResultBlock):
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                    "is_error": block.is_error,
                }
            )
        else:  # TextBlock
            blocks.append({"type": "text", "text": block.text})
    return blocks


def _to_wire(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    """Split into (system, messages). Role.TOOL turns map to user tool_result turns."""
    system_parts: list[str] = []
    wire: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.role.value if isinstance(msg.role, Role) else msg.role
        if role == Role.SYSTEM.value:
            system_parts.append(msg.text())
            continue
        wire_role = "user" if role in (Role.USER.value, Role.TOOL.value) else "assistant"
        wire.append({"role": wire_role, "content": _content_to_wire(msg)})
    system = "\n\n".join(p for p in system_parts if p) or None
    return system, wire


class AnthropicProvider(HttpProvider):
    name = "anthropic"
    is_local = False

    def __init__(self, *, api_key: str, base_url: str, timeout_s: float = 120.0) -> None:
        super().__init__(
            base_url=base_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            timeout_s=timeout_s,
        )

    def _build_payload(self, params: GenerateParams, *, stream: bool) -> dict[str, Any]:
        system, messages = _to_wire(params.messages)
        payload: dict[str, Any] = {
            "model": params.model,
            "max_tokens": params.max_tokens,
            "messages": messages,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        if params.temperature is not None:
            payload["temperature"] = params.temperature
        if params.tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in params.tools
            ]
        return payload

    async def generate(self, params: GenerateParams) -> Completion:
        payload = self._build_payload(params, stream=False)

        async def _call() -> httpx.Response:
            return await self._post("/v1/messages", payload, timeout_s=params.timeout_s)

        resp = await retry_async(_call, is_retryable=is_retryable_http, retries=self._retries)
        data = resp.json()
        return self._parse_message(data)

    def _parse_message(self, data: dict[str, Any]) -> Completion:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(id=block["id"], name=block["name"], arguments=block.get("input", {}))
                )
        usage_raw = data.get("usage", {})
        return Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=_STOP_MAP.get(data.get("stop_reason", ""), StopReason.END_TURN),
            usage=Usage(
                input_tokens=usage_raw.get("input_tokens"),
                output_tokens=usage_raw.get("output_tokens"),
            ),
            model=data.get("model"),
        )

    async def stream(self, params: GenerateParams) -> AsyncIterator[Any]:
        from sobai.core.types import StreamEvent, StreamEventType

        payload = self._build_payload(params, stream=True)
        text_parts: list[str] = []
        tool_partials: dict[int, dict[str, Any]] = {}
        usage = Usage()
        stop_reason = StopReason.END_TURN
        model = params.model
        try:
            async with self._client.stream(
                "POST", "/v1/messages", json=payload, timeout=params.timeout_s
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if not raw:
                        continue
                    event = json.loads(raw)
                    etype = event.get("type")
                    if etype == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            tool_partials[event["index"]] = {
                                "id": block["id"],
                                "name": block["name"],
                                "json": "",
                            }
                    elif etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text", "")
                            text_parts.append(chunk)
                            yield StreamEvent(type=StreamEventType.TEXT, text=chunk)
                        elif delta.get("type") == "input_json_delta":
                            idx = event["index"]
                            if idx in tool_partials:
                                tool_partials[idx]["json"] += delta.get("partial_json", "")
                    elif etype == "message_delta":
                        d = event.get("delta", {})
                        if d.get("stop_reason"):
                            stop_reason = _STOP_MAP.get(d["stop_reason"], StopReason.END_TURN)
                        u = event.get("usage", {})
                        if u:
                            usage = Usage(
                                input_tokens=u.get("input_tokens", usage.input_tokens),
                                output_tokens=u.get("output_tokens", usage.output_tokens),
                            )
                    elif etype == "message_stop":
                        break
        except httpx.HTTPStatusError as exc:
            raise self._wrap_status_error(exc) from exc
        except httpx.TransportError as exc:
            raise self._wrap_transport_error(exc) from exc

        tool_calls = [
            ToolCall(
                id=p["id"],
                name=p["name"],
                arguments=json.loads(p["json"]) if p["json"] else {},
            )
            for p in tool_partials.values()
        ]
        completion = Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
            model=model,
        )
        yield StreamEvent(type=StreamEventType.DONE, completion=completion)

    async def list_models(self) -> list[ModelInfo]:
        resp = await self._get("/v1/models")
        data = resp.json()
        return [
            ModelInfo(
                id=m["id"],
                provider=self.name,
                display_name=m.get("display_name"),
            )
            for m in data.get("data", [])
        ]

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
