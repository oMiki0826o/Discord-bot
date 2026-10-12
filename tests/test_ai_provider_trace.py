"""
tests/test_ai_provider_trace.py

Modification():

- 提供 test ai provider trace 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import asyncio

import pytest

from bot.mod.ai.provider.errors import ProviderError
from bot.mod.ai.provider.models import GenerationRequest, ProviderPolicy, ProviderResponse, TokenUsage
from bot.mod.ai.provider.quota import QuotaManager
from bot.mod.ai.provider.runtime import ProviderRuntime


def test_generic_provider_error_is_recorded_in_the_request_trace() -> None:
    class Transport:
        async def generate(self, request, model):
            del request, model
            raise ProviderError("malformed provider response")

        async def close(self):
            return None

    traces: list[tuple[str, str, str, str]] = []
    runtime = ProviderRuntime(Transport(), quota=QuotaManager(default_cooldown_seconds=60), trace_recorder=lambda *args: traces.append(args))
    request = GenerationRequest(
        request_id="request", user_id="user", prompt="hello", system_instruction="system",
        model_candidates=("model",), policy=ProviderPolicy(retries_per_model=1),
    )

    with pytest.raises(ProviderError):
        asyncio.run(runtime.generate(request))

    assert traces == [("request", "user", "model", "provider_error")]


def test_successful_response_survives_usage_and_trace_recorder_failures() -> None:
    class Transport:
        async def generate(self, request, model):
            del request
            return ProviderResponse("answer", model, usage=TokenUsage(7, 3, 10))

        async def close(self):
            return None

    def broken(*args):
        del args
        raise OSError("database unavailable")

    runtime = ProviderRuntime(
        Transport(),
        quota=QuotaManager(default_cooldown_seconds=60),
        usage_recorder=broken,
        trace_recorder=broken,
    )
    request = GenerationRequest(
        request_id="request", user_id="user", prompt="hello", system_instruction="system",
        model_candidates=("model",), policy=ProviderPolicy(retries_per_model=1),
    )

    response = asyncio.run(runtime.generate(request))

    assert response.text == "answer"
