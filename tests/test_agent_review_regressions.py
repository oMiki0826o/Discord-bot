"""
tests/test_agent_review_regressions.py

Modification():
- Reproduce mixed Gemini text/function-call turns being returned too early.
- Reproduce concurrent Discord requests bypassing a pending Redis guard.
"""

from __future__ import annotations

import asyncio

import pytest

from bot.mod.agent.config import AgentSettings
from bot.mod.agent.runtime import AgentRuntime, ModelTurn
from bot.mod.agent.tools import Tool, ToolCall, ToolRegistry
from bot.mod.ai.guard import GuardBusyError, RequestGuard
from bot.mod.ai.runtime.models import RuntimeRequest


def test_agent_executes_tool_even_if_model_turn_also_contains_text() -> None:
    calls: list[str] = []

    class MixedModel:
        async def generate_turn(self, request, transcript, declarations, *, allow_tools):
            del request, declarations
            if not transcript:
                assert allow_tools
                return ModelTurn(
                    final_text="I will search now.",
                    function_calls=(ToolCall("look_up", {}),),
                    model="test",
                )
            assert transcript[-1]["role"] == "tool"
            return ModelTurn(final_text="Verified answer from lookup.", model="test")

    async def lookup(args, context):
        del args, context
        calls.append("lookup")
        return {"source": "verified"}

    tools = ToolRegistry()
    tools.register(Tool("look_up", "Read verified facts", "knowledge", frozenset(), lookup))
    runtime = AgentRuntime(
        MixedModel(), tools,
        AgentSettings(max_model_turns=3, max_tool_calls=2, total_timeout_seconds=5, tool_timeout_seconds=1),
    )
    req = RuntimeRequest(
        request_id="one", user_id="alice", channel_id="general", prompt="Search for facts",
        model_candidates=("test",), capabilities=frozenset({"knowledge"}),
    )
    result = asyncio.run(runtime.run(req))
    assert calls == ["lookup"]
    assert result.tool_calls == 1
    assert result.text == "Verified answer from lookup."


def test_same_user_cannot_bypass_guard_while_awaiting_redis() -> None:
    async def run() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        class BlockingLimiter:
            async def allow(self, user_id: str) -> bool:
                del user_id
                entered.set()
                await release.wait()
                return True

        guard = RequestGuard(
            cooldown_seconds=0,
            abuse_limit=8,
            abuse_window_seconds=60,
            distributed_limiter=BlockingLimiter(),
        )
        first = asyncio.create_task(guard.acquire("same-user", prompt="first"))
        await entered.wait()
        other = asyncio.create_task(guard.acquire("same-user", prompt="second"))
        await asyncio.sleep(0)
        release.set()
        permit = await first
        with pytest.raises(GuardBusyError):
            await other
        permit.release(success=True)

    asyncio.run(run())
