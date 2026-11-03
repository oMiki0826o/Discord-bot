"""bot/mod/dmcc/services/event_queue.py

Modification():

- Decouple authenticated Gateway parsing from bounded Discord HTTP delivery.

"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from ..events import MinecraftEvent

logger = logging.getLogger(__name__)


class EventForwarder(Protocol):
    async def forward(self, event: MinecraftEvent) -> bool: ...


class DiscordEventQueue:
    """A bounded ordered queue; Discord I/O never blocks the Bridge read loop."""

    def __init__(self, forwarder: EventForwarder, *, capacity: int = 256) -> None:
        if capacity < 1:
            raise ValueError("Discord event queue capacity must be positive")
        self._forwarder = forwarder
        self._queue: asyncio.Queue[MinecraftEvent] = asyncio.Queue(maxsize=capacity)
        self._task: asyncio.Task[None] | None = None
        self._accepting = False
        self._stopped = False
        self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    @property
    def stopped(self) -> bool:
        return self._stopped

    def start(self) -> None:
        if self._task is not None or self._stopped:
            raise RuntimeError("Discord event queue already started or stopped")
        self._accepting = True
        self._task = asyncio.create_task(self._run(), name="dmcc-discord-events")

    async def publish(self, event: MinecraftEvent) -> bool:
        if not self._accepting:
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 100 == 0:
                logger.warning(
                    "DMCC Discord event queue full; dropped=%s server=%s event=%s",
                    self._dropped, event.server_id, event.type,
                )
            return False

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._forwarder.forward(event)
            except Exception:
                logger.exception(
                    "DMCC Discord event delivery failed server=%s event=%s",
                    event.server_id, event.type,
                )
            finally:
                self._queue.task_done()

    async def close(self, *, timeout: float = 2.0) -> None:
        self._accepting = False
        if self._stopped:
            return
        self._stopped = True
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("DMCC Discord event queue could not drain before shutdown")
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            while not self._queue.empty():
                self._queue.get_nowait()
                self._queue.task_done()
