"""
tests/test_ai_service_autonomous_sources.py

Modification():

- 驗證 AI 先查本機 Knowledge；查無資料才為資訊問題開放 Web fallback。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.mod.ai.context.models import ContextItem, ContextPack, ContextSource
from bot.mod.ai.guard import RequestGuard
from bot.mod.ai.routing import Router
from bot.mod.ai.runtime.models import RuntimeResult, RuntimeStopReason
from bot.mod.ai.service import AIRequest, AIService


class _Events:
    def append(self, _event) -> None:
        return None


class _Planner:
    def __init__(self, context: ContextPack) -> None:
        self.context = context

    async def build(self, *_args, **_kwargs) -> ContextPack:
        return self.context


class _Prompts:
    def load(self):
        return object()


class _Composer:
    def compose(self, **_kwargs):
        return SimpleNamespace(system_instruction="system", context_blocks=())


class _Runtime:
    def __init__(self) -> None:
        self.request = None

    async def run(self, request):
        self.request = request
        return RuntimeResult("answer", RuntimeStopReason.COMPLETED, 1, 0, 0, "test")


class _MemoryJobs:
    def enqueue(self, *_args, **_kwargs) -> None:
        return None


def _service(context: ContextPack) -> tuple[AIService, _Runtime]:
    runtime = _Runtime()
    service = AIService(
        settings=SimpleNamespace(
            context_max_tokens=200,
            recent_message_limit=4,
            model_pools={"chat": ("chat-model",), "search": ("search-model",)},
        ),
        events=_Events(),
        context=object(),
        context_planner=_Planner(context),
        prompts=_Prompts(),
        composer=_Composer(),
        router=Router(),
        guard=RequestGuard(cooldown_seconds=0, abuse_limit=10, abuse_window_seconds=60),
        runtime=runtime,
        memory_jobs=_MemoryJobs(),
    )
    return service, runtime


def _request() -> AIRequest:
    return AIRequest("request", "user", "channel", "conversation", "message", "太陽牌代表什麼？", 1)


def test_information_request_without_local_knowledge_enables_web_fallback() -> None:
    service, runtime = _service(ContextPack((), 0, 200, 0))

    asyncio.run(service.generate(_request()))

    assert "web" in runtime.request.capabilities
    assert runtime.request.model_candidates == ("search-model",)
    assert "Local Knowledge returned no relevant evidence" in runtime.request.system_instruction


def test_information_request_with_local_knowledge_does_not_enable_web() -> None:
    knowledge = ContextItem(
        "knowledge:card", "knowledge:card", ContextSource.KNOWLEDGE, "太陽牌", 0.9, 4, 1.0, 0, 2,
    )
    service, runtime = _service(ContextPack((knowledge,), 2, 200, 0))

    asyncio.run(service.generate(_request()))

    assert "web" not in runtime.request.capabilities
    assert runtime.request.model_candidates == ("chat-model",)
