from __future__ import annotations

import httpx
import respx

from sobai.core.types import GenerateParams, Message, StopReason, StreamEventType, ToolSpec
from sobai.providers.anthropic import AnthropicProvider
from sobai.providers.ollama import OllamaProvider
from sobai.providers.openai import OpenAIProvider

PARAMS = GenerateParams(model="m", messages=[Message.user("hi")], system="sys")


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
async def test_anthropic_generate_text() -> None:
    body = {
        "id": "msg",
        "type": "message",
        "role": "assistant",
        "model": "claude-x",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Hello"}],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    with respx.mock(base_url="https://api.anthropic.com") as mock:
        route = mock.post("/v1/messages").mock(return_value=httpx.Response(200, json=body))
        provider = AnthropicProvider(
            api_key="sk-ant-test1234", base_url="https://api.anthropic.com"
        )
        result = await provider.generate(PARAMS)
        await provider.aclose()
    assert result.text == "Hello"
    assert result.usage.input_tokens == 5
    assert route.calls.last.request.headers["x-api-key"] == "sk-ant-test1234"
    assert route.calls.last.request.headers["anthropic-version"] == "2023-06-01"


async def test_anthropic_tool_use() -> None:
    body = {
        "stop_reason": "tool_use",
        "model": "claude-x",
        "content": [{"type": "tool_use", "id": "tu1", "name": "echo", "input": {"x": "1"}}],
        "usage": {},
    }
    with respx.mock(base_url="https://api.anthropic.com") as mock:
        mock.post("/v1/messages").mock(return_value=httpx.Response(200, json=body))
        provider = AnthropicProvider(api_key="k123456", base_url="https://api.anthropic.com")
        params = PARAMS.model_copy(
            update={
                "tools": [ToolSpec(name="echo", description="e", input_schema={"type": "object"})]
            }
        )
        result = await provider.generate(params)
        await provider.aclose()
    assert result.stop_reason is StopReason.TOOL_USE
    assert result.tool_calls[0].name == "echo"
    assert result.tool_calls[0].arguments == {"x": "1"}


async def test_anthropic_auth_error() -> None:
    with respx.mock(base_url="https://api.anthropic.com") as mock:
        mock.post("/v1/messages").mock(
            return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
        )
        provider = AnthropicProvider(api_key="badkey123", base_url="https://api.anthropic.com")
        import pytest

        from sobai.core.errors import ProviderError

        with pytest.raises(ProviderError):
            await provider.generate(PARAMS)
        await provider.aclose()


async def test_anthropic_stream() -> None:
    sse = (
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"He"}}\n\n'
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"llo"}}\n\n'
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
        '"usage":{"output_tokens":2}}\n\n'
        'data: {"type":"message_stop"}\n\n'
    )
    with respx.mock(base_url="https://api.anthropic.com") as mock:
        mock.post("/v1/messages").mock(return_value=httpx.Response(200, content=sse.encode()))
        provider = AnthropicProvider(api_key="k123456", base_url="https://api.anthropic.com")
        chunks = []
        completion = None
        async for ev in provider.stream(PARAMS):
            if ev.type is StreamEventType.TEXT:
                chunks.append(ev.text)
            elif ev.type is StreamEventType.DONE:
                completion = ev.completion
        await provider.aclose()
    assert "".join(chunks) == "Hello"
    assert completion is not None
    assert completion.text == "Hello"


# --------------------------------------------------------------------------- #
# OpenAI (Responses API)
# --------------------------------------------------------------------------- #
async def test_openai_generate_text() -> None:
    body = {
        "id": "resp",
        "object": "response",
        "status": "completed",
        "model": "gpt-x",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hi there"}],
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 4},
    }
    with respx.mock(base_url="https://api.openai.com/v1") as mock:
        route = mock.post("/responses").mock(return_value=httpx.Response(200, json=body))
        provider = OpenAIProvider(api_key="sk-openai-test", base_url="https://api.openai.com/v1")
        result = await provider.generate(PARAMS)
        await provider.aclose()
    assert result.text == "Hi there"
    assert result.usage.output_tokens == 4
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-openai-test"


async def test_openai_tool_call() -> None:
    body = {
        "status": "completed",
        "model": "gpt-x",
        "output": [
            {"type": "function_call", "call_id": "c1", "name": "echo", "arguments": '{"x": 1}'}
        ],
        "usage": {},
    }
    with respx.mock(base_url="https://api.openai.com/v1") as mock:
        mock.post("/responses").mock(return_value=httpx.Response(200, json=body))
        provider = OpenAIProvider(api_key="sk-openai-test", base_url="https://api.openai.com/v1")
        result = await provider.generate(PARAMS)
        await provider.aclose()
    assert result.stop_reason is StopReason.TOOL_USE
    assert result.tool_calls[0].name == "echo"
    assert result.tool_calls[0].arguments == {"x": 1}


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #
async def test_ollama_generate() -> None:
    body = {
        "model": "qwen",
        "message": {"role": "assistant", "content": "Hi"},
        "done": True,
        "prompt_eval_count": 4,
        "eval_count": 2,
    }
    with respx.mock(base_url="http://localhost:11434") as mock:
        mock.post("/api/chat").mock(return_value=httpx.Response(200, json=body))
        provider = OllamaProvider(base_url="http://localhost:11434")
        result = await provider.generate(PARAMS)
        await provider.aclose()
    assert result.text == "Hi"
    assert result.usage.input_tokens == 4
    assert provider.is_local is True


async def test_ollama_tool_call_and_models() -> None:
    chat = {
        "model": "qwen",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "echo", "arguments": {"x": 1}}}],
        },
        "done": True,
    }
    tags = {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "qwen3-coder:30b"}]}
    with respx.mock(base_url="http://localhost:11434") as mock:
        mock.post("/api/chat").mock(return_value=httpx.Response(200, json=chat))
        mock.get("/api/tags").mock(return_value=httpx.Response(200, json=tags))
        provider = OllamaProvider(base_url="http://localhost:11434")
        result = await provider.generate(PARAMS)
        models = await provider.list_models()
        await provider.aclose()
    assert result.tool_calls[0].name == "echo"
    assert [m.id for m in models] == ["qwen2.5-coder:7b", "qwen3-coder:30b"]


async def test_ollama_stream_ndjson() -> None:
    ndjson = (
        '{"message":{"content":"He"},"done":false}\n'
        '{"message":{"content":"llo"},"done":false}\n'
        '{"message":{"content":""},"done":true,"prompt_eval_count":1,"eval_count":2}\n'
    )
    with respx.mock(base_url="http://localhost:11434") as mock:
        mock.post("/api/chat").mock(return_value=httpx.Response(200, content=ndjson.encode()))
        provider = OllamaProvider(base_url="http://localhost:11434")
        text = ""
        async for ev in provider.stream(PARAMS):
            if ev.type is StreamEventType.TEXT:
                text += ev.text
        await provider.aclose()
    assert text == "Hello"
