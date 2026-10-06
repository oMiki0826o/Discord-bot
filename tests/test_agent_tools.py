"""
tests/test_agent_tools.py

Modification():

- 驗證 Agent tool loop 的只讀工具、簽章與重複呼叫保護。
- 驗證 Gemini 3 組合工具回合完整保留 provider context。
"""

from __future__ import annotations

import asyncio

from bot.mod.agent.config import AgentSettings
from bot.mod.agent.builtin_tools import build_readonly_registry
from bot.mod.agent.runtime import AgentRuntime, ModelTurn
from bot.mod.agent.tools import Tool, ToolCall, ToolContext, ToolRegistry
from bot.mod.ai.knowledge.service import KnowledgeChunk, KnowledgeHit
from bot.mod.ai.runtime.models import RuntimeRequest


class _EmptyToolModel:
    def __init__(self) -> None:
        self.turns = 0

    async def generate_turn(self, request, transcript, declarations, *, allow_tools):
        del request, transcript, declarations
        self.turns += 1
        if self.turns == 1:
            assert allow_tools
            return ModelTurn(function_calls=(ToolCall("empty", {}),), model="test")
        return ModelTurn(final_text="should not be requested", model="test")


class _KnowledgeRetryModel:
    def __init__(self) -> None:
        self.turns = 0

    async def generate_turn(self, request, transcript, declarations, *, allow_tools):
        del request, declarations
        self.turns += 1
        if self.turns == 1:
            assert allow_tools
            return ModelTurn(function_calls=(ToolCall("knowledge", {"query": "natural wording"}),), model="test")
        if self.turns == 2:
            assert transcript[-1]["results"][0][1].data == ()
            return ModelTurn(function_calls=(ToolCall("knowledge", {"query": "server main"}),), model="test")
        return ModelTurn(final_text="found it", model="test")


def test_agent_stops_after_empty_tool_observation() -> None:
    async def empty_handler(arguments, context):
        del arguments, context
        return ()

    registry = ToolRegistry()
    registry.register(Tool("empty", "returns nothing", "time", frozenset(), empty_handler))
    model = _EmptyToolModel()
    runtime = AgentRuntime(model, registry, AgentSettings(max_model_turns=3, max_tool_calls=3, tool_timeout_seconds=1, total_timeout_seconds=5))
    request = RuntimeRequest(
        request_id="request",
        user_id="user",
        channel_id="channel",
        prompt="prompt",
        guild_id="guild",
        system_instruction="system",
        model_candidates=("test",),
        capabilities=frozenset({"time"}),
    )

    result = asyncio.run(runtime.run(request))

    assert result.tool_calls == 1
    assert model.turns == 1
    assert result.text == "Available information is insufficient for a reliable answer."


def test_agent_allows_knowledge_search_to_rephrase_after_empty_result() -> None:
    async def handler(arguments, context):
        del context
        return () if arguments["query"] == "natural wording" else ({"source_file": "minecraft/server/Main.java"},)

    registry = ToolRegistry()
    registry.register(Tool(
        "knowledge", "knowledge search", "knowledge", frozenset({"query"}), handler,
        required_argument_names=frozenset({"query"}), retry_on_empty=True,
    ))
    runtime = AgentRuntime(
        _KnowledgeRetryModel(), registry,
        AgentSettings(max_model_turns=4, max_tool_calls=4, tool_timeout_seconds=1, total_timeout_seconds=5),
    )
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="prompt",
        system_instruction="system", model_candidates=("test",), capabilities=frozenset({"knowledge"}),
    )

    result = asyncio.run(runtime.run(request))

    assert result.text == "found it"
    assert result.model_turns == 3
    assert result.tool_calls == 2


def test_agent_tool_output_is_bounded_before_returning_to_the_model() -> None:
    async def handler(arguments, context):
        del arguments, context
        return "x" * 100

    registry = ToolRegistry()
    registry.register(Tool("bounded", "bounded output", "time", frozenset(), handler, max_output_chars=20))
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="prompt",
        guild_id="guild", system_instruction="system", model_candidates=("test",), capabilities=frozenset({"time"}),
    )

    result = asyncio.run(registry.execute(ToolCall("bounded", {}), ToolContext(request, request.capabilities, 1)))

    assert result.ok
    assert result.data == "x" * 20


def test_tool_argument_schema_rejects_wrong_scalar_type_before_handler() -> None:
    calls = 0

    async def handler(arguments, context):
        nonlocal calls
        del arguments, context
        calls += 1
        return "ok"

    registry = ToolRegistry()
    registry.register(Tool(
        "limit", "uses an integer limit", "time", frozenset({"limit"}), handler,
        required_argument_names=frozenset({"limit"}), argument_types={"limit": "integer"},
    ))
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="prompt",
        guild_id="guild", system_instruction="system", model_candidates=("test",), capabilities=frozenset({"time"}),
    )

    result = asyncio.run(registry.execute(ToolCall("limit", {"limit": "5"}), ToolContext(request, request.capabilities, 1)))

    assert result.error == "invalid_arguments"
    assert calls == 0
    assert registry.declarations(frozenset({"time"}))[0]["parameters"]["properties"]["limit"]["type"] == "integer"


def test_knowledge_tool_labels_the_file_separately_from_chunk_id() -> None:
    class Services:
        async def search_knowledge(self, query, *, limit):
            assert query == "MinecraftServer"
            assert limit == 6
            return (KnowledgeHit(KnowledgeChunk("knowledge_chunk", "minecraft/server/Main.java", "class Main {}"), 1.0),)

    registry = build_readonly_registry(Services())
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="prompt",
        system_instruction="system", model_candidates=("test",), capabilities=frozenset({"knowledge"}),
    )

    result = asyncio.run(registry.execute(
        ToolCall("search_knowledge", {"query": "MinecraftServer"}),
        ToolContext(request, request.capabilities, 1),
    ))

    assert result.ok
    assert result.data == (
        {"chunk_id": "knowledge_chunk", "source_file": "minecraft/server/Main.java", "content": "class Main {}"},
    )
    declaration = next(item for item in registry.declarations(frozenset({"knowledge"})) if item["name"] == "search_knowledge")
    assert "English identifiers" in declaration["description"]


def test_agent_preserves_provider_thought_signature_in_the_tool_transcript() -> None:
    """Gemini 3 rejects a follow-up tool result without its original signature."""

    class _SignatureModel:
        def __init__(self) -> None:
            self.turns = 0

        async def generate_turn(self, request, transcript, declarations, *, allow_tools):
            del request, declarations
            self.turns += 1
            if self.turns == 1:
                assert allow_tools
                return ModelTurn(
                    function_calls=(ToolCall("lookup", {}, thought_signature=b"signature"),),
                    model="test",
                )
            assert transcript[0]["function_calls"][0].thought_signature == b"signature"
            return ModelTurn(final_text="verified", model="test")

    async def handler(arguments, context):
        del arguments, context
        return {"source": "local"}

    registry = ToolRegistry()
    registry.register(Tool("lookup", "lookup", "knowledge", frozenset(), handler))
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="prompt",
        system_instruction="system", model_candidates=("test",), capabilities=frozenset({"knowledge"}),
    )

    result = asyncio.run(AgentRuntime(
        _SignatureModel(), registry,
        AgentSettings(max_model_turns=3, max_tool_calls=2, tool_timeout_seconds=1, total_timeout_seconds=5),
    ).run(request))

    assert result.text == "verified"


def test_agent_preserves_full_provider_tool_context_in_the_tool_transcript() -> None:
    """Combined Gemini tools require the original server-side tool parts on turn two."""

    provider_content = object()

    class _ContextModel:
        def __init__(self) -> None:
            self.turns = 0

        async def generate_turn(self, request, transcript, declarations, *, allow_tools):
            del request, declarations
            self.turns += 1
            if self.turns == 1:
                assert allow_tools
                return ModelTurn(
                    function_calls=(ToolCall("lookup", {}),),
                    model="test",
                    provider_content=provider_content,
                )
            assert transcript[0]["provider_content"] is provider_content
            return ModelTurn(final_text="verified", model="test")

    async def handler(arguments, context):
        del arguments, context
        return {"source": "local"}

    registry = ToolRegistry()
    registry.register(Tool("lookup", "lookup", "knowledge", frozenset(), handler))
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="prompt",
        system_instruction="system", model_candidates=("test",), capabilities=frozenset({"knowledge"}),
    )

    result = asyncio.run(AgentRuntime(
        _ContextModel(), registry,
        AgentSettings(max_model_turns=3, max_tool_calls=2, tool_timeout_seconds=1, total_timeout_seconds=5),
    ).run(request))

    assert result.text == "verified"
