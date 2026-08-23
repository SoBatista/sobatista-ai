"""Coverage for streaming, message conversion, and HTTP error wrapping."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from sobai.core.errors import ProviderError, ProviderUnavailableError
from sobai.core.types import (
    GenerateParams,
    Message,
    Role,
    StopReason,
    StreamEventType,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from sobai.providers.anthropic import AnthropicProvider
from sobai.providers.ollama import OllamaProvider
from sobai.providers.openai import OpenAIProvider

BASE_ANT = "https://api.anthropic.com"
BASE_OAI = "https://api.openai.com/v1"
PARAMS = GenerateParams(model="m", messages=[Message.user("hi")], system="sys")


# --------------------------------------------------------------------------- #
# Message conversion
# --------------------------------------------------------------------------- #
def _tool_conversation() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content=[TextBlock(text="be nice")]),
        Message.user("do it"),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c1", name="echo", input={"x": 1})]),
        Message(role=Role.TOOL, content=[ToolResultBlock(tool_use_id="c1", content="42")]),
    ]


async def test_anthropic_conversion_system_and_tool_result() -> None:
    body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}], "usage": {}}
    with respx.mock(base_url=BASE_ANT) as mock:
        route = mock.post("/v1/messages").mock(return_value=httpx.Response(200, json=body))
        provider = AnthropicProvider(api_key="k123456", base_url=BASE_ANT)
        await provider.generate(PARAMS.model_copy(update={"messages": _tool_conversation()}))
        await provider.aclose()
    sent = json.loads(route.calls.last.request.content)
    assert sent["system"] == "sys\n\nbe nice" or "be nice" in sent["system"]
    # tool result becomes a user-role tool_result block
    roles = [m["role"] for m in sent["messages"]]
    assert "assistant" in roles and roles.count("user") >= 2
    assert any(b.get("type") == "tool_result" for m in sent["messages"] for b in m["content"])


async def test_openai_conversion_function_items_and_schema() -> None:
    body = {"status": "completed", "output": [], "usage": {}}
    with respx.mock(base_url=BASE_OAI) as mock:
        route = mock.post("/responses").mock(return_value=httpx.Response(200, json=body))
        provider = OpenAIProvider(api_key="sk-x", base_url=BASE_OAI)
        params = PARAMS.model_copy(
            update={
                "messages": _tool_conversation(),
                "response_schema": {"type": "object", "properties": {"a": {"type": "string"}}},
                "tools": [ToolSpec(name="echo", description="e", input_schema={"type": "object"})],
            }
        )
        await provider.generate(params)
        await provider.aclose()
    sent = json.loads(route.calls.last.request.content)
    types = [item.get("type") for item in sent["input"]]
    assert "function_call" in types
    assert "function_call_output" in types
    assert sent["instructions"]
    assert sent["text"]["format"]["type"] == "json_schema"
    assert sent["tools"][0]["type"] == "function"


# --------------------------------------------------------------------------- #
# OpenAI streaming
# --------------------------------------------------------------------------- #
async def test_openai_stream() -> None:
    completed = {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "model": "gpt-x",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hello"}],
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
    }
    sse = (
        'data: {"type":"response.output_text.delta","delta":"Hel"}\n\n'
        'data: {"type":"response.output_text.delta","delta":"lo"}\n\n'
        f"data: {json.dumps(completed)}\n\n"
    )
    with respx.mock(base_url=BASE_OAI) as mock:
        mock.post("/responses").mock(return_value=httpx.Response(200, content=sse.encode()))
        provider = OpenAIProvider(api_key="sk-x", base_url=BASE_OAI)
        text = ""
        done = None
        async for ev in provider.stream(PARAMS):
            if ev.type is StreamEventType.TEXT:
                text += ev.text
            elif ev.type is StreamEventType.DONE:
                done = ev.completion
        await provider.aclose()
    assert text == "Hello"
    assert done is not None and done.text == "Hello"


async def test_openai_stream_error() -> None:
    sse = 'data: {"type":"response.failed","error":{"message":"boom"}}\n\n'
    with respx.mock(base_url=BASE_OAI) as mock:
        mock.post("/responses").mock(return_value=httpx.Response(200, content=sse.encode()))
        provider = OpenAIProvider(api_key="sk-x", base_url=BASE_OAI)
        with pytest.raises(ProviderError):
            async for _ in provider.stream(PARAMS):
                pass
        await provider.aclose()


# --------------------------------------------------------------------------- #
# Anthropic streaming tool use
# --------------------------------------------------------------------------- #
async def test_anthropic_stream_tool_use() -> None:
    sse = (
        'data: {"type":"content_block_start","index":0,'
        '"content_block":{"type":"tool_use","id":"tu1","name":"echo"}}\n\n'
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"input_json_delta","partial_json":"{\\"x\\":"}}\n\n'
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"input_json_delta","partial_json":"1}"}}\n\n'
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
        '"usage":{"output_tokens":1}}\n\n'
        'data: {"type":"message_stop"}\n\n'
    )
    with respx.mock(base_url=BASE_ANT) as mock:
        mock.post("/v1/messages").mock(return_value=httpx.Response(200, content=sse.encode()))
        provider = AnthropicProvider(api_key="k123456", base_url=BASE_ANT)
        done = None
        async for ev in provider.stream(PARAMS):
            if ev.type is StreamEventType.DONE:
                done = ev.completion
        await provider.aclose()
    assert done is not None
    assert done.stop_reason is StopReason.TOOL_USE
    assert done.tool_calls[0].name == "echo"
    assert done.tool_calls[0].arguments == {"x": 1}


# --------------------------------------------------------------------------- #
# HTTP error wrapping
# --------------------------------------------------------------------------- #
async def test_http_404_wrapped() -> None:
    with respx.mock(base_url=BASE_ANT) as mock:
        mock.post("/v1/messages").mock(return_value=httpx.Response(404, text="nope"))
        provider = AnthropicProvider(api_key="k123456", base_url=BASE_ANT)
        with pytest.raises(ProviderError) as exc:
            await provider.generate(PARAMS)
        await provider.aclose()
    assert "404" in str(exc.value)


async def test_http_transport_error_wrapped() -> None:
    with respx.mock(base_url="http://localhost:11434") as mock:
        mock.post("/api/chat").mock(side_effect=httpx.ConnectError("refused"))
        provider = OllamaProvider(base_url="http://localhost:11434")
        with pytest.raises(ProviderUnavailableError):
            await provider.generate(PARAMS)
        await provider.aclose()


async def test_ollama_tool_result_conversion() -> None:
    from sobai.providers.ollama import _to_ollama

    wire = _to_ollama(_tool_conversation())
    roles = [m["role"] for m in wire]
    assert "tool" in roles
    assert any(m.get("tool_calls") for m in wire)
