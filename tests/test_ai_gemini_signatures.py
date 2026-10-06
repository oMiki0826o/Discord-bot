"""
tests/test_ai_gemini_signatures.py

Modification():

- 驗證 Gemini 3 的搜尋與 Function Calling 組合工具設定。
- 驗證後續回合保留完整 provider tool context 與 function call ID。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from google.genai import types

from bot.mod.agent.tools import ToolCall, ToolResult
from bot.mod.ai.provider.gemini import GeminiTransport
from bot.mod.ai.provider.models import GenerationRequest


class _Models:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        part = types.Part.from_function_call(name="lookup", args={"query": "CCE"})
        part.thought_signature = b"signed-thought"
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
            text="",
        )


def _request(*, transcript=()):
    return GenerationRequest(
        request_id="request", user_id="user", prompt="prompt", system_instruction="system",
        model_candidates=("gemini-test",), tools=({"name": "lookup"},), transcript=transcript,
    )


def test_gemini_transport_round_trips_function_call_thought_signature() -> None:
    models = _Models()
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    transport = GeminiTransport("", client=client)

    first = asyncio.run(transport.generate(_request(), "gemini-test"))

    assert first.tool_calls[0].thought_signature == b"signed-thought"
    transcript = (
        {"role": "model", "function_calls": (ToolCall("lookup", {"query": "CCE"}, b"signed-thought"),)},
        {"role": "tool", "results": ((ToolCall("lookup", {"query": "CCE"}, b"signed-thought"), ToolResult(True, {"ok": True})),)},
    )
    asyncio.run(transport.generate(_request(transcript=transcript), "gemini-test"))

    function_call_part = models.calls[1]["contents"][1].parts[0]
    assert function_call_part.thought_signature == b"signed-thought"


def test_gemini_transport_excludes_builtin_search_when_function_tools_exist() -> None:
    models = _Models()
    transport = GeminiTransport("", client=SimpleNamespace(aio=SimpleNamespace(models=models)))
    request = GenerationRequest(
        request_id="request", user_id="user", prompt="prompt", system_instruction="system",
        model_candidates=("gemini-test",), tools=({"name": "lookup"},), use_web=True,
    )

    asyncio.run(transport.generate(request, "gemini-test"))

    tools = models.calls[0]["config"]["tools"]
    assert tools == [{"function_declarations": [{"name": "lookup"}]}]


def test_gemini_transport_combines_search_for_an_enabled_gemini_3_request() -> None:
    models = _Models()
    transport = GeminiTransport("", client=SimpleNamespace(aio=SimpleNamespace(models=models)))
    request = GenerationRequest(
        request_id="request", user_id="user", prompt="prompt", system_instruction="system",
        model_candidates=("gemini-3-flash-preview",), tools=({"name": "lookup"},),
        use_web=True, allow_combined_tools=True,
    )

    asyncio.run(transport.generate(request, "gemini-3-flash-preview"))

    config = models.calls[0]["config"]
    assert config["tools"] == [{"google_search": {}, "function_declarations": [{"name": "lookup"}]}]
    assert config["tool_config"] == {"include_server_side_tool_invocations": True}


def test_gemini_transport_replays_full_provider_content_for_combined_tool_follow_up() -> None:
    models = _Models()
    provider_content = SimpleNamespace(parts=[SimpleNamespace(tool_call={"id": "google-search"})])
    transport = GeminiTransport("", client=SimpleNamespace(aio=SimpleNamespace(models=models)))
    request = GenerationRequest(
        request_id="request", user_id="user", prompt="prompt", system_instruction="system",
        model_candidates=("gemini-3-flash-preview",), tools=({"name": "lookup"},), use_web=True,
        allow_combined_tools=True,
        transcript=(
            {"role": "model", "provider_content": provider_content},
            {"role": "tool", "results": ((ToolCall("lookup", {}, call_id="call-1"), ToolResult(True, {"ok": True})),)},
        ),
    )

    asyncio.run(transport.generate(request, "gemini-3-flash-preview"))

    contents = models.calls[0]["contents"]
    assert contents[1] is provider_content
    assert contents[2].parts[0].function_response.id == "call-1"
