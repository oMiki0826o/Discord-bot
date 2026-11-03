"""
tests/test_ai_redis_limiter.py

Modification():
- Verify Redis-backed counters, denied requests, and safe local fallback.
"""
from __future__ import annotations

import asyncio

import pytest

from bot.mod.ai.cache.redis_limiter import RedisRateLimiter
from bot.mod.ai.guard import GuardRejectedError, RequestGuard


class FakeRedis:
    def __init__(self):
        self.calls = []
        self.count = 0
        self.closed = False
        self.fail = False

    async def eval(self, code, numkeys, key, window_seconds):
        if self.fail:
            raise ConnectionError("offline")
        self.calls.append((code, numkeys, key, window_seconds))
        self.count += 1
        return self.count

    async def aclose(self):
        self.closed = True


def test_redis_limiter_uses_hashed_ids_and_honours_budget() -> None:
    async def run():
        redis = FakeRedis()
        limiter = RedisRateLimiter(redis, max_requests=2, window_seconds=60)
        assert await limiter.allow("123") is True
        assert await limiter.allow("123") is True
        assert await limiter.allow("123") is False
        assert all("123" not in key for _, _, key, _ in redis.calls)
        assert all(key.startswith("discord-ai:rate:") for _, _, key, _ in redis.calls)
        await limiter.aclose()
        assert redis.closed
    asyncio.run(run())


def test_unavailable_redis_falls_back_to_local_guard() -> None:
    async def run():
        redis = FakeRedis()
        redis.fail = True
        limiter = RedisRateLimiter(redis, max_requests=1, window_seconds=60)
        guard = RequestGuard(cooldown_seconds=0, abuse_limit=2, abuse_window_seconds=60,
                             distributed_limiter=limiter)
        permit1 = await guard.acquire("one", prompt="hello")
        permit1.release(success=True)
        permit2 = await guard.acquire("one", prompt="hello")
        permit2.release(success=True)
        with pytest.raises(GuardRejectedError):
            await guard.acquire("one", prompt="hello")
        await guard.aclose()
        assert redis.closed
    asyncio.run(run())


def test_redis_rejection_is_enforced_before_local_request_reservation() -> None:
    async def run():
        redis = FakeRedis()
        limiter = RedisRateLimiter(redis, max_requests=1, window_seconds=60)
        guard = RequestGuard(cooldown_seconds=0, abuse_limit=5, abuse_window_seconds=60,
                             distributed_limiter=limiter)
        first = await guard.acquire("one", prompt="hello")
        first.release(success=True)
        with pytest.raises(GuardRejectedError, match="distributed"):
            await guard.acquire("one", prompt="hello")
        assert "one" not in guard._active
        await guard.aclose()
    asyncio.run(run())
