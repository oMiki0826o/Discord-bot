"""
bot/mod/ai/guard.py

Modification():

- 建立跨 Discord 入口共用的 user lock、cooldown、abuse 與 prompt guard。

本檔案防止使用者交替使用 mention/slash 繞過請求限制。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable


class GuardError(RuntimeError):
    """Base error for a rejected AI request."""


class GuardBusyError(GuardError):
    """The requester already has an active AI request."""


class GuardRejectedError(GuardError):
    """The request violates a configured safety or rate limit."""


class GuardPermit:
    def __init__(self, guard: "RequestGuard", user_id: str) -> None:
        self._guard = guard
        self.user_id = user_id
        self._released = False

    def release(self, *, success: bool) -> None:
        if self._released:
            return
        self._released = True
        self._guard._release(self.user_id, success=success)

    async def __aenter__(self) -> "GuardPermit":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.release(success=exc_type is None)


class RequestGuard:
    def __init__(self, *, cooldown_seconds: float, abuse_limit: int, abuse_window_seconds: float, max_prompt_chars: int = 20_000, clock: Callable[[], float] = time.monotonic, is_blocked: Callable[[str], str | None] | None = None) -> None:
        if cooldown_seconds < 0 or abuse_limit < 1 or abuse_window_seconds <= 0 or max_prompt_chars < 1:
            raise ValueError("Guard settings are invalid")
        self.cooldown_seconds = cooldown_seconds
        self.abuse_limit = abuse_limit
        self.abuse_window_seconds = abuse_window_seconds
        self.max_prompt_chars = max_prompt_chars
        self._clock = clock
        self._is_blocked = is_blocked
        self._active: set[str] = set()
        self._last_success: dict[str, float] = {}
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def acquire(self, user_id: str, *, prompt: str) -> GuardPermit:
        if not user_id.strip() or not prompt.strip():
            raise GuardRejectedError("prompt is empty")
        if len(prompt) > self.max_prompt_chars:
            raise GuardRejectedError("prompt is too long")
        blocked = None if self._is_blocked is None else self._is_blocked(user_id)
        if blocked is not None:
            raise GuardRejectedError(f"user is {blocked}")
        if user_id in self._active:
            raise GuardBusyError("another request is active")
        now = self._clock()
        if now - self._last_success.get(user_id, float("-inf")) < self.cooldown_seconds:
            raise GuardRejectedError("request is on cooldown")
        records = self._requests[user_id]
        threshold = now - self.abuse_window_seconds
        while records and records[0] <= threshold:
            records.popleft()
        if len(records) >= self.abuse_limit:
            raise GuardRejectedError("too many requests")
        records.append(now)
        self._active.add(user_id)
        return GuardPermit(self, user_id)

    def _release(self, user_id: str, *, success: bool) -> None:
        self._active.discard(user_id)
        if success:
            self._last_success[user_id] = self._clock()

    def clear(self) -> None:
        self._active.clear()
        self._last_success.clear()
        self._requests.clear()
