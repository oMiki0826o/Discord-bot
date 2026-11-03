"""
tests/test_ai_redis_knowledge_cache.py

Modification():
- Verify public Redis cache re-reads current sources and fails over safely.
"""
from __future__ import annotations

import asyncio

from bot.mod.ai.cache.knowledge import RedisKnowledgeCache
from bot.mod.ai.knowledge.service import KnowledgeChunk, KnowledgeHit


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}
        self.keys = []
        self.fail = False
        self.closed = False

    async def get(self, key):
        self.keys.append(key)
        if self.fail:
            raise ConnectionError("unavailable")
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        if self.fail:
            raise ConnectionError("unavailable")
        assert ex <= 300
        self.values[key] = value

    async def aclose(self):
        self.closed = True


class FakeRetrieval:
    def __init__(self):
        self.search_calls = 0
        self.valid = True

    async def search_knowledge(self, query, *, limit):
        self.search_calls += 1
        return (KnowledgeHit(KnowledgeChunk("chunk1", "public.md", "public data"), 0.95),)

    def read_knowledge_chunk(self, chunk_id):
        if not self.valid:
            return None
        return KnowledgeChunk("chunk1", "public.md", "public data") if chunk_id == "chunk1" else None


def test_public_knowledge_cache_contains_only_hashes_and_chunk_ids() -> None:
    async def run():
        r = FakeRetrieval()
        redis = FakeRedis()
        cache = RedisKnowledgeCache(redis)
        first = await cache.search("public query", limit=6, retrieval=r)
        second = await cache.search("public query", limit=6, retrieval=r)
        assert len(first) == len(second) == 1
        assert r.search_calls == 1
        assert "public query" not in str(redis.values)
        assert all(key.startswith("discord-ai:public-knowledge:v1:") for key in redis.keys)
        await cache.aclose()
        assert redis.closed
    asyncio.run(run())


def test_deleted_knowledge_source_forces_fresh_retrieval() -> None:
    async def run():
        r, redis = FakeRetrieval(), FakeRedis()
        cache = RedisKnowledgeCache(redis)
        await cache.search("public query", limit=6, retrieval=r)
        r.valid = False
        await cache.search("public query", limit=6, retrieval=r)
        assert r.search_calls == 2
    asyncio.run(run())


def test_redis_connection_failure_never_blocks_knowledge_search() -> None:
    async def run():
        r, redis = FakeRetrieval(), FakeRedis()
        redis.fail = True
        hits = await RedisKnowledgeCache(redis).search("public query", limit=6, retrieval=r)
        assert hits[0].chunk.source_id == "public.md"
        assert r.search_calls == 1
    asyncio.run(run())
