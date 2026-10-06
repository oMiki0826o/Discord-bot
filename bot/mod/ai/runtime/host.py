"""
bot/mod/ai/runtime/host.py

Modification():

- 建立同一時間僅執行一個 Runtime 的 capability host。
- 保留 extension factory，AI reload 後以新 services 重建附掛 Runtime。
- 保留單次 Provider request 錯誤，不將 Agent Runtime 降級為 BasicRuntime。

本檔不理解任何特定 Agent 實作。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from .models import RuntimeResult, RuntimeStopReason
from .protocol import AiRuntime
from ..provider.errors import ProviderError, ProviderQuotaError

RuntimeFactory = Callable[[Any], AiRuntime]
logger = logging.getLogger("bot.mod.ai.runtime_host")


@dataclass(frozen=True, slots=True)
class RuntimeRegistration:
    factory: RuntimeFactory
    read_only: bool


class RuntimeHost:
    def __init__(self) -> None:
        self._basic: AiRuntime | None = None
        self._active: AiRuntime | None = None
        self._services: Any = None
        self._extensions: dict[str, RuntimeRegistration] = {}
        self._active_owner: str | None = None

    @property
    def active(self) -> AiRuntime:
        if self._active is None:
            raise RuntimeError("AI runtime host is not bound")
        return self._active

    @property
    def services(self) -> Any:
        if self._services is None:
            raise RuntimeError("AI runtime host is not bound")
        return self._services

    def bind(self, basic: AiRuntime, services: Any) -> None:
        if self._basic is not None or self._active is not None:
            raise RuntimeError("AI runtime host is already bound")
        active = basic
        active_owner = None
        if self._extensions:
            owner = next(reversed(self._extensions))
            active = self._extensions[owner].factory(services)
            active_owner = owner
        self._basic = basic
        self._services = services
        self._active = active
        self._active_owner = active_owner

    def register(self, owner: str, factory: RuntimeFactory, *, read_only: bool = False) -> AiRuntime:
        normalized = owner.strip()
        if not normalized:
            raise ValueError("runtime extension owner must not be blank")
        if normalized in self._extensions:
            raise ValueError(f"runtime extension already registered: {normalized}")
        if self._extensions:
            raise RuntimeError("AI runtime extension slot is already occupied")
        services = self.services
        runtime = factory(services)
        self._extensions[normalized] = RuntimeRegistration(factory, read_only)
        self._active = runtime
        self._active_owner = normalized
        return runtime

    def unregister(self, owner: str) -> AiRuntime:
        normalized = owner.strip()
        if normalized not in self._extensions:
            raise KeyError(f"runtime extension is not registered: {normalized}")
        self._extensions.pop(normalized)
        removed = self.active
        if self._basic is None:
            raise RuntimeError("AI runtime host is not bound")
        self._active = self._basic
        self._active_owner = None
        return removed

    async def run(self, request):
        active = self.active
        if active is self._basic or self._active_owner is None:
            return await active.run(request)
        registration = self._extensions[self._active_owner]
        try:
            result = await active.run(request)
        except (ProviderQuotaError, ProviderError):
            # A provider quota failure is shared by the basic and extension
            # runtimes. Retrying through BasicRuntime only spends another API
            # call and hides the actual cause, so preserve provider errors.
            raise
        except Exception:
            if not registration.read_only or self._basic is None:
                raise
            logger.exception(
                "Read-only runtime extension failed; falling back to BasicRuntime owner=%s",
                self._active_owner,
            )
            return await self._basic.run(request)
        if (
            registration.read_only
            and isinstance(result, RuntimeResult)
            and result.stop_reason is RuntimeStopReason.FAILED
            and self._basic is not None
        ):
            logger.warning(
                "Read-only runtime extension returned failed status; falling back to BasicRuntime owner=%s",
                self._active_owner,
            )
            return await self._basic.run(request)
        return result

    async def close(self) -> None:
        active = self._active
        basic = self._basic
        self._active = None
        self._basic = None
        self._services = None
        self._active_owner = None
        try:
            if active is not None and active is not basic:
                await active.close()
        finally:
            if basic is not None:
                await basic.close()
