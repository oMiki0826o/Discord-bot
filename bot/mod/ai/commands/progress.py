"""
bot/mod/ai/commands/progress.py
Modification():
- Render real execution events in a throttled Discord-native status message.
- Replace the status with the final answer, without emojis or simulated thoughts.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from ..runtime.events import ProgressEvent

logger = logging.getLogger(__name__)


class ProgressReporter:
    def __init__(
        self,
        send: Callable[[str], Awaitable[Any]],
        edit: Callable[[Any, str], Awaitable[None]],
        *,
        delay_seconds: float = 1.5,
        throttle_seconds: float = 1.5,
    ) -> None:
        self._send = send
        self._edit = edit
        self._delay = delay_seconds
        self._throttle = throttle_seconds
        self._events: list[str] = ["已接收問題"]
        self._message: Any = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._last_edit = 0.0
        self._finished = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._delayed_start())

    async def _delayed_start(self) -> None:
        await asyncio.sleep(self._delay)
        async with self._lock:
            if self._finished or self._message is not None:
                return
            try:
                self._message = await self._send(self._render())
            except Exception:
                logger.warning("Unable to display AI progress", exc_info=True)
                return
            self._last_edit = monotonic()

    def _render(self) -> str:
        return "正在處理...\n\n" + "\n".join(self._events[-6:])

    async def publish(self, event: ProgressEvent) -> None:
        if self._finished:
            return
        async with self._lock:
            if self._finished:
                return
            if event.label and (not self._events or event.label != self._events[-1]):
                self._events.append(event.label[:150])
            if self._message is None or monotonic() - self._last_edit < self._throttle:
                return
            try:
                await self._edit(self._message, self._render())
                self._last_edit = monotonic()
            except Exception:
                logger.warning("Unable to update AI progress", exc_info=True)

    async def finish(self, content: str) -> bool:
        self._finished = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        async with self._lock:
            if self._message is None:
                return False
            try:
                await self._edit(self._message, content)
            except Exception:
                logger.warning("Unable to replace AI progress with final answer", exc_info=True)
                return False
            return True
