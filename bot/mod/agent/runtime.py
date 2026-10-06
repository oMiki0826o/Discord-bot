"""
bot/mod/agent/runtime.py

Modification():

- 建立可附掛至 AI RuntimeHost 的有限預算 Agent Tool Loop。
- 防止重複 Tool Call，並在預算用盡後強制收尾。
- 保留 Provider 原始 tool context，支援 Gemini 3 server-side tool circulation。

本 Runtime 不擁有 Provider、Database 或 Discord 入口。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from ..ai.api import RuntimeRequest, RuntimeResult, RuntimeStopReason

from .config import AgentSettings
from .tools import ToolCall, ToolContext, ToolRegistry, ToolResult


@dataclass(frozen=True, slots=True)
class ModelTurn:
    final_text: str = ""
    function_calls: tuple[ToolCall, ...] = ()
    model: str = ""
    provider_content: Any = field(default=None, repr=False, compare=False)


class AgentModel(Protocol):
    async def generate_turn(self, request: RuntimeRequest, transcript: Sequence[dict[str, Any]], declarations: tuple[dict[str, object], ...], *, allow_tools: bool) -> ModelTurn: ...


class AgentRuntime:
    def __init__(self, model: AgentModel, registry: ToolRegistry, settings: AgentSettings) -> None:
        self.model = model
        self.registry = registry
        self.settings = settings

    async def run(self, request: RuntimeRequest) -> RuntimeResult:
        started = perf_counter()
        try:
            async with asyncio.timeout(self.settings.total_timeout_seconds):
                return await self._run(request, started)
        except TimeoutError:
            return self._result("AI request timed out", RuntimeStopReason.FAILED, 0, 0, started)

    async def close(self) -> None:
        close = getattr(self.model, "close", None)
        if close is not None:
            await close()

    async def _run(self, request: RuntimeRequest, started: float) -> RuntimeResult:
        transcript: list[dict[str, Any]] = []
        seen: set[str] = set()
        observations: list[str] = []
        model_turns = 0
        tool_calls = 0
        used_model = ""
        force_final = False
        while model_turns < self.settings.max_model_turns:
            allow_tools = bool(request.capabilities) and tool_calls < self.settings.max_tool_calls and not force_final
            declarations = self.registry.declarations(request.capabilities) if allow_tools else ()
            model_turns += 1
            turn = await self.model.generate_turn(request, transcript, declarations, allow_tools=allow_tools)
            used_model = turn.model or used_model
            if turn.final_text.strip():
                reason = RuntimeStopReason.FORCED_FINALIZE if force_final else RuntimeStopReason.COMPLETED
                return self._result(turn.final_text.strip(), reason, model_turns, tool_calls, started, used_model, tuple(observations))
            if not allow_tools or not turn.function_calls:
                break
            transcript.append(
                {"role": "model", "provider_content": turn.provider_content}
                if turn.provider_content is not None
                else {"role": "model", "function_calls": turn.function_calls}
            )
            results: list[tuple[ToolCall, ToolResult]] = []
            context = ToolContext(request, request.capabilities, self.settings.tool_timeout_seconds)
            for call in turn.function_calls:
                if tool_calls >= self.settings.max_tool_calls:
                    force_final = True
                    break
                if call.fingerprint in seen:
                    results.append((call, ToolResult(False, error="duplicate_tool_call", observation_id=call.fingerprint[:16])))
                    force_final = True
                    continue
                seen.add(call.fingerprint)
                tool_calls += 1
                result = await self.registry.execute(call, context)
                results.append((call, result))
                if result.observation_id not in observations:
                    observations.append(result.observation_id)
                if (
                    result.ok
                    and self._is_empty_observation(result.data)
                    and not self.registry.retries_on_empty(call.name)
                ):
                    force_final = True
            transcript.append({"role": "tool", "results": tuple(results)})
            if force_final:
                break
            if tool_calls >= self.settings.max_tool_calls:
                force_final = True
        return self._result(
            "Available information is insufficient for a reliable answer.",
            RuntimeStopReason.FORCED_FINALIZE,
            model_turns,
            tool_calls,
            started,
            used_model,
            tuple(observations),
        )

    @staticmethod
    def _is_empty_observation(value: Any) -> bool:
        """Stop a tool loop when a successful tool has no usable observation."""

        return value is None or value == "" or value == () or value == [] or value == {}

    @staticmethod
    def _result(text: str, reason: RuntimeStopReason, model_turns: int, tool_calls: int, started: float, model: str = "", observation_ids: tuple[str, ...] = ()) -> RuntimeResult:
        return RuntimeResult(text, reason, model_turns, tool_calls, max(0, round((perf_counter() - started) * 1000)), model, observation_ids, True)
