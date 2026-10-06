"""
tests/test_ai_runtime_host.py

Modification():

- 驗證單次 ProviderError 不會讓 Agent Runtime 降級為 BasicRuntime。

本檔驗證 RuntimeHost 的 extension fallback 邊界。
"""

from __future__ import annotations

import asyncio

import pytest

from bot.mod.ai.provider.errors import ProviderError
from bot.mod.ai.runtime.host import RuntimeHost


class _ProviderFailureRuntime:
    async def run(self, request):
        del request
        raise ProviderError("invalid request")

    async def close(self) -> None:
        return None


class _BasicRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request):
        del request
        self.calls += 1
        return "basic"

    async def close(self) -> None:
        return None


def test_provider_error_keeps_read_only_extension_active() -> None:
    host = RuntimeHost()
    basic = _BasicRuntime()
    host.bind(basic, object())
    host.register("agent", lambda _services: _ProviderFailureRuntime(), read_only=True)

    with pytest.raises(ProviderError):
        asyncio.run(host.run(object()))

    assert basic.calls == 0
