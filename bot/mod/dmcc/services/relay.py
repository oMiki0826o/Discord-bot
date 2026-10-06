"""bot/mod/dmcc/services/relay.py

bot/mod/dmcc/dmcc/services/relay.py

Modification():

- 提供 DMCC Gateway 與未來 Discord Adapter 之間的事件 Relay 邊界。

本檔不依賴 Discord 或 Minecraft API。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..events import MinecraftEvent


# ── Relay Service ──────────────────────


RelayHandler = Callable[[MinecraftEvent], Awaitable[None]]


class RelayService:
    """將已驗證的 Minecraft 事件交給已訂閱的非同步處理器。"""

    def __init__(self) -> None:
        self._handlers: list[RelayHandler] = []

    def subscribe(self, handler: RelayHandler) -> None:
        """註冊一個 Relay 處理器；同一 callable 只會加入一次。"""

        if handler not in self._handlers:
            self._handlers.append(handler)

    async def publish(self, event: MinecraftEvent) -> None:
        """依註冊順序送出事件，避免隱藏的背景任務與例外。"""

        for handler in tuple(self._handlers):
            await handler(event)
