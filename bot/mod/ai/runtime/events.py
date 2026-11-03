"""
bot/mod/ai/runtime/events.py
Modification():
- Emit verifiable, non-sensitive runtime progress events for Discord.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: str
    label: str


ProgressSink = Callable[[ProgressEvent], Awaitable[None]]


async def notify(sink: ProgressSink | None, kind: str, label: str) -> None:
    if sink is None:
        return
    try:
        await sink(ProgressEvent(kind, label))
    except Exception:
        logger.warning("Progress listener failed at %s", kind, exc_info=True)
