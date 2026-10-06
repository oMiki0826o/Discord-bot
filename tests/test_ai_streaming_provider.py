"""
tests/test_ai_streaming_provider.py

Modification():

- 提供 test ai streaming provider 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import asyncio

from bot.mod.ai.provider.gemini import GeminiTransport
from bot.mod.ai.provider.quota import QuotaManager
from bot.mod.ai.provider.models import GenerationRequest
from bot.mod.ai.provider.runtime import ProviderRuntime


def test_gemini_transport_stream_yields_nonempty_text_chunks() -> None:
    class Models:
        async def generate_content_stream(self, **kwargs):
            del kwargs
            for text in ("hello", "", " world"):
                yield type("Chunk", (), {"text": text})()

    class Client:
        aio = type("Aio", (), {"models": Models()})()

    transport = GeminiTransport("", client=Client())
    request = GenerationRequest(
        request_id="request", user_id="user", prompt="prompt", system_instruction="system",
        model_candidates=("model",),
    )

    async def collect() -> tuple[str, ...]:
        return tuple([chunk async for chunk in transport.stream(request, "model")])

    assert asyncio.run(collect()) == ("hello", " world")


def test_provider_runtime_stream_records_success_after_complete_stream() -> None:
    class Transport:
        async def stream(self, request, model):
            del request, model
            yield "first"
            yield " second"

        async def close(self):
            return None

    traces = []
    runtime = ProviderRuntime(Transport(), quota=QuotaManager(default_cooldown_seconds=60), trace_recorder=lambda *entry: traces.append(entry))
    request = GenerationRequest(request_id="request", user_id="user", prompt="prompt", system_instruction="system", model_candidates=("model",))

    async def collect() -> tuple[str, ...]:
        return tuple([item async for item in runtime.stream(request)])

    assert asyncio.run(collect()) == ("first", " second")
    assert traces == [("request", "user", "model", "success")]
