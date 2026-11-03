"""
bot/mod/ai/cache/__init__.py

Modification():
- Expose a safe, optional Redis-backed distributed rate limiter.
"""
from .redis_limiter import RedisRateLimiter

__all__ = ("RedisRateLimiter",)
