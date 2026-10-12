"""
tests/test_ai_retrieval.py

Modification():

- 驗證 Knowledge embedding 依內容與模型重用。
"""

from __future__ import annotations

import asyncio

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.knowledge.service import KnowledgeDocument, KnowledgeService
from bot.mod.ai.retrieval.service import HybridRetrievalService
from bot.mod.ai.retrieval.vector import VectorRepository


def test_unchanged_chunk_reuses_embedding_for_the_same_model(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    knowledge = KnowledgeService(database, chunk_chars=500)
    vectors = VectorRepository(database)
    calls: list[str] = []

    async def embedder(content: str) -> tuple[float, ...]:
        calls.append(content)
        return (1.0, 0.0)

    retrieval = HybridRetrievalService(
        knowledge=knowledge,
        vectors=vectors,
        embedder=embedder,
        embedding_model="embed-v1",
    )
    document = KnowledgeDocument("guide.md", "Guide", "same content", "guide.md")

    asyncio.run(retrieval.index_document(document, now=1))
    asyncio.run(retrieval.index_document(document, now=2))

    assert calls == ["same content"]


def test_embedding_is_refreshed_when_the_model_changes(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    knowledge = KnowledgeService(database, chunk_chars=500)
    vectors = VectorRepository(database)
    calls: list[str] = []

    async def embedder(content: str) -> tuple[float, ...]:
        calls.append(content)
        return (1.0, 0.0)

    document = KnowledgeDocument("guide.md", "Guide", "same content", "guide.md")
    first = HybridRetrievalService(knowledge=knowledge, vectors=vectors, embedder=embedder, embedding_model="v1")
    second = HybridRetrievalService(knowledge=knowledge, vectors=vectors, embedder=embedder, embedding_model="v2")

    asyncio.run(first.index_document(document, now=1))
    asyncio.run(second.index_document(document, now=2))

    assert calls == ["same content", "same content"]
