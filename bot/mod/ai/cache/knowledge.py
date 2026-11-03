"""
bot/mod/ai/cache/knowledge.py

Modification():
- Cache only verified public knowledge chunk identifiers in Redis.
- Re-validate every cached hit against current Knowledge sources before use.
- Degrade to the existing hybrid retriever when Redis is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import logging

from ..knowledge.service import KnowledgeHit

logger = logging.getLogger(__name__)


class RedisKnowledgeCache:
    def __init__(self, client, *, ttl_seconds: int = 30) -> None:
        if not 1 <= ttl_seconds <= 300:
            raise ValueError("Invalid Knowledge cache TTL")
        self.client = client
        self.ttl_seconds = ttl_seconds

    @classmethod
    def from_url(cls, url: str):
        if not url.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError("Invalid AI_REDIS_URL")
        from redis.asyncio import Redis
        return cls(Redis.from_url(
            url, socket_timeout=0.6, socket_connect_timeout=0.6,
            max_connections=4, decode_responses=True,
        ))

    async def search(self, query: str, *, limit: int, retrieval):
        if not query.strip() or not 1 <= limit <= 20:
            return await retrieval.search_knowledge(query, limit=limit)
        # This key never stores the raw query or requester's identity.
        digest = hashlib.sha256(f"{limit}:{query.casefold().strip()}".encode()).hexdigest()
        key = "discord-ai:public-knowledge:v1:" + digest
        try:
            raw = await self.client.get(key)
            if raw:
                chunk_ids = json.loads(raw)
                if isinstance(chunk_ids, list) and all(
                    isinstance(entry, dict)
                    and isinstance(entry.get("id"), str)
                    and 0 < len(entry["id"]) <= 128
                    and isinstance(entry.get("score"), (int, float))
                    and isinstance(entry.get("title"), str)
                    and isinstance(entry.get("title_match"), int)
                    for entry in chunk_ids
                ):
                    verified = []
                    for entry in chunk_ids:
                        # Re-read the authoritative source before using cached metadata.
                        chunk = retrieval.read_knowledge_chunk(entry["id"])
                        if chunk is None:
                            break
                        verified.append(KnowledgeHit(
                            chunk, float(entry["score"]),
                            entry["title"][:256], entry["title_match"],
                        ))
                    if verified and len(verified) == len(chunk_ids):
                        return tuple(verified)
        except Exception:
            logger.warning("Redis Knowledge cache unavailable; querying index directly")

        hits = await retrieval.search_knowledge(query, limit=limit)
        if hits:
            try:
                await self.client.set(
                    key, json.dumps([
                        {"id": hit.chunk.chunk_id, "score": hit.score,
                         "title": hit.title, "title_match": hit.title_match}
                        for hit in hits
                    ]),
                    ex=self.ttl_seconds,
                )
            except Exception:
                logger.warning("Redis Knowledge cache unavailable; returning direct results")
        return hits

    async def aclose(self) -> None:
        try:
            await self.client.aclose()
        except Exception:
            logger.warning("Unable to close Redis Knowledge cache")
