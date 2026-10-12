"""
bot/mod/ai/retrieval/service.py

Modification():

- 建立 Knowledge FTS + Embedding + RRF 混合檢索。
- Embedding 失敗時保留 FTS 結果，不讓查詢整體失敗。

本檔案是 Agent Tool 的統一 Knowledge retrieval 入口。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .fusion import rrf_fuse

logger = logging.getLogger("bot.mod.ai.retrieval")
Embedder = Callable[[str], Awaitable[tuple[float, ...]]]


class HybridRetrievalService:
    def __init__(self, *, knowledge: Any, vectors: Any, memory: Any = None, manual_memory: Any = None, knowledge_sources: Any = None, embedder: Embedder | None = None, embedding_model: str = "") -> None:
        self.knowledge = knowledge
        self.vectors = vectors
        self.memory = memory
        self.manual_memory = manual_memory
        self.knowledge_sources = knowledge_sources
        self.embedder = embedder
        self.embedding_model = embedding_model

    async def search_user_memory(self, *, user_id: str, channel_id: str, query: str, limit: int = 20) -> tuple[dict[str, Any], ...]:
        """在 Runtime 注入的使用者與頻道範圍內查詢 private memory。"""

        if self.memory is None and self.manual_memory is None:
            return ()
        from ..history.lexical import normalize_lexical_document
        from ..memory.models import MemoryQuery, MemoryScopeType

        query_tokens = set(normalize_lexical_document(query).split())
        memories = () if self.memory is None else (
            self.memory.find_active(MemoryQuery(user_id, MemoryScopeType.GLOBAL, user_id, limit=limit))
            + self.memory.find_active(MemoryQuery(user_id, MemoryScopeType.CHANNEL, channel_id, limit=limit))
        )
        ranked: list[tuple[int, int, int, Any]] = []
        for item in memories:
            searchable = normalize_lexical_document(
                f"{item.memory_type} {item.memory_key} "
                + json.dumps(item.value, ensure_ascii=False, sort_keys=True)
            )
            score = len(query_tokens.intersection(searchable.split()))
            if query_tokens and score == 0:
                continue
            ranked.append((score, item.importance, item.updated_at, item))
        ranked.sort(key=lambda entry: (-entry[0], -entry[1], -entry[2], entry[3].memory_id))
        automatic = tuple({
            "type": item.memory_type,
            "key": item.memory_key,
            "value": item.value,
            "confidence": item.confidence,
            "importance": item.importance,
            "updated_at": item.updated_at,
        } for _score, _importance, _updated, item in ranked[:limit])
        manual = () if self.manual_memory is None else tuple({
            "type": item["category"] if isinstance(item, dict) else item.memory_type,
            "key": item["memory_key"] if isinstance(item, dict) else item.key,
            "value": item["content"] if isinstance(item, dict) else item.value,
            "confidence": float(item["confidence"]) if isinstance(item, dict) else 1.0,
            "importance": int(item["importance"]) if isinstance(item, dict) else item.importance,
            "updated_at": item["updated_at"] if isinstance(item, dict) else 0,
            "source_file": item["source_path"] if isinstance(item, dict) else item.source_file,
            "source_kind": "manual_file",
        } for item in self.manual_memory.search(user_id=user_id, query=query, limit=limit))
        return (manual + automatic)[:limit]

    async def index_document(self, document: Any, *, now: int) -> tuple[str, ...]:
        chunk_ids = self.knowledge.index(document, now=now)
        if self.embedder is None:
            return chunk_ids
        for chunk_id in chunk_ids:
            chunk = self.knowledge.read_chunk(chunk_id)
            if chunk is None:
                continue
            digest = hashlib.sha256(chunk.content.encode()).hexdigest()
            if self.vectors.matches(
                source_kind="knowledge",
                item_id=chunk_id,
                model=self.embedding_model,
                content_hash=digest,
            ):
                continue
            try:
                vector = await self.embedder(chunk.content)
            except Exception:
                logger.warning("Embedding index failed for %s; FTS remains available", chunk_id, exc_info=True)
                continue
            self.vectors.upsert(source_kind="knowledge", item_id=chunk_id, vector=vector, model=self.embedding_model, content_hash=digest, now=now)
        return chunk_ids

    async def search_knowledge(self, query: str, *, limit: int = 6):
        lexical = self.knowledge.search(query, limit=max(limit, 20))
        title_matched = tuple(hit for hit in lexical if hit.title_match > 0)
        if title_matched:
            # A direct title match is stronger evidence than a semantic hit in
            # a changelog or quoted discussion.  Keeping this branch lexical
            # also avoids spending an embedding request on an already exact
            # lookup.
            return self._verify_knowledge_hits(title_matched, limit=limit)
        if self.embedder is None:
            return self._verify_knowledge_hits(lexical, limit=limit)
        try:
            vector = await self.embedder(query)
            nearest = await asyncio.to_thread(
                self.vectors.nearest,
                source_kind="knowledge",
                query=vector,
                model=self.embedding_model,
                limit=max(limit, 20),
            )
            vector_ranking = tuple(item_id for item_id, _score in nearest)
        except Exception:
            logger.warning("Embedding retrieval unavailable; falling back to FTS", exc_info=True)
            return self._verify_knowledge_hits(lexical, limit=limit)
        by_id = {hit.chunk.chunk_id: hit for hit in lexical}
        fused = rrf_fuse((tuple(by_id), vector_ranking))
        results = []
        for item_id, _score in fused:
            hit = by_id.get(item_id)
            if hit is None:
                chunk = self.knowledge.read_chunk(item_id)
                if chunk is not None:
                    from ..knowledge.service import KnowledgeHit
                    hit = KnowledgeHit(chunk, 0.0)
            if hit is not None:
                results.append(hit)
            if len(results) >= limit:
                break
        # Preserve direct article-title matches ahead of semantic-only or
        # changelog hits.  The remaining order still follows RRF.
        results.sort(key=lambda hit: -hit.title_match)
        return self._verify_knowledge_hits(tuple(results), limit=limit)

    def read_knowledge_chunk(self, chunk_id: str):
        if self.knowledge_sources is None:
            return self.knowledge.read_chunk(chunk_id)
        return self.knowledge.read_verified_chunk(chunk_id, source_reader=self.knowledge_sources)

    def _verify_knowledge_hits(self, hits: tuple[Any, ...], *, limit: int) -> tuple[Any, ...]:
        if self.knowledge_sources is None:
            return tuple(hits[:limit])
        from ..knowledge.service import KnowledgeHit
        verified = []
        for hit in hits:
            chunk = self.knowledge.read_verified_chunk(hit.chunk.chunk_id, source_reader=self.knowledge_sources)
            if chunk is not None:
                verified.append(KnowledgeHit(chunk, hit.score, hit.title, hit.title_match))
            if len(verified) >= limit:
                break
        return tuple(verified)
