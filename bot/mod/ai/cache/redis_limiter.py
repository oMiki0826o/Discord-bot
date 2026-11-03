"""
bot/mod/ai/cache/redis_limiter.py

Modification():
- Store only hashed requester IDs and short-lived counters in Redis.
- Fail over to the existing per-process guard on Redis failures.
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

_INCREMENT = """
local value = redis.call('INCR', KEYS[1])
if value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return value
"""


class RedisRateLimiter:
    def __init__(self, client, *, max_requests: int, window_seconds: int) -> None:
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("Rate limit settings must be positive")
        self.client = client
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    @classmethod
    def from_url(cls, url: str, *, max_requests: int, window_seconds: int):
        if not url or not url.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError("Invalid AI_REDIS_URL")
        from redis.asyncio import Redis

        return cls(
            Redis.from_url(url, socket_connect_timeout=0.6, socket_timeout=0.6,
                           max_connections=4, decode_responses=True),
            max_requests=max_requests, window_seconds=window_seconds,
        )

    async def allow(self, user_id: str) -> bool | None:
        # Never use raw IDs, prompts, knowledge or private memory as Redis keys.
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        try:
            count = int(await self.client.eval(
                _INCREMENT, 1, "discord-ai:rate:" + digest, self.window_seconds,
            ))
        except Exception:
            logger.warning("Redis unavailable: retaining local rate limiter", exc_info=True)
            return None
        return count <= self.max_requests

    async def aclose(self) -> None:
        try:
            await self.client.aclose()
        except Exception:
            logger.warning("Unable to close Redis rate limiter", exc_info=True)
