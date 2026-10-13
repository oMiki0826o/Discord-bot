"""
bot/mod/ai/knowledge/staging.py
Modification(): 建立 Knowledge/Embedding 暫存索引，驗證完成後以短交易原子發布。
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable

from ..database import AiDatabase
from ..history.lexical import normalize_lexical_document
from ..retrieval.vector import pack_vector
from .chunking import chunk_markdown
from .service import KnowledgeDocument

Embedder = Callable[[str], Awaitable[tuple[float, ...]]]


class KnowledgeStagingSession:
    """Build a replacement Knowledge dataset without touching active query tables."""

    def __init__(
        self,
        database: AiDatabase,
        *,
        chunk_chars: int,
        embedder: Embedder | None,
        embedding_model: str,
    ) -> None:
        self.database = database
        self.chunk_chars = chunk_chars
        self.embedder = embedder
        self.embedding_model = embedding_model

    def seed_active(self) -> None:
        with self.database.transaction() as connection:
            self._clear(connection)
            connection.execute(
                "INSERT INTO knowledge_sources_staging SELECT * FROM knowledge_sources"
            )
            connection.execute(
                "INSERT INTO knowledge_chunks_staging SELECT * FROM knowledge_chunks"
            )
            connection.execute(
                "INSERT INTO knowledge_search_staging "
                "SELECT chunk_id, source_id, search_text FROM knowledge_search"
            )
            connection.execute(
                "INSERT INTO retrieval_embeddings_staging "
                "SELECT * FROM retrieval_embeddings WHERE source_kind = 'knowledge'"
            )

    async def apply_document(self, document: KnowledgeDocument, *, now: int | None = None) -> int:
        indexed_at = int(time.time()) if now is None else now
        digest = hashlib.sha256(document.content.encode()).hexdigest()
        chunks = chunk_markdown(document.content, max_chars=self.chunk_chars)
        with self.database.transaction() as connection:
            self._remove_source(connection, document.source_id)
            connection.execute(
                "INSERT INTO knowledge_sources_staging "
                "(source_id,title,origin,content_hash,indexed_at) VALUES (?,?,?,?,?)",
                (document.source_id, document.title, document.origin, digest, indexed_at),
            )

        occurrences: dict[str, int] = {}
        for ordinal, content in enumerate(chunks):
            chunk_digest = hashlib.sha256(content.encode()).hexdigest()
            occurrence = occurrences.get(chunk_digest, 0)
            occurrences[chunk_digest] = occurrence + 1
            chunk_id = "knowledge_" + hashlib.sha256(
                f"{document.source_id}:{chunk_digest}:{occurrence}".encode()
            ).hexdigest()[:24]
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO knowledge_chunks_staging "
                    "(chunk_id,source_id,ordinal,content,content_hash) VALUES (?,?,?,?,?)",
                    (chunk_id, document.source_id, ordinal, content, chunk_digest),
                )
                connection.execute(
                    "INSERT INTO knowledge_search_staging (chunk_id,source_id,search_text) "
                    "VALUES (?,?,?)",
                    (
                        chunk_id,
                        document.source_id,
                        normalize_lexical_document(document.title + "\n" + content),
                    ),
                )
                reused = connection.execute(
                    "SELECT * FROM retrieval_embeddings WHERE source_kind='knowledge' "
                    "AND item_id=? AND model=? AND content_hash=?",
                    (chunk_id, self.embedding_model, chunk_digest),
                ).fetchone()
                if reused is not None:
                    connection.execute(
                        "INSERT INTO retrieval_embeddings_staging VALUES (?,?,?,?,?,?,?,?,?)",
                        tuple(reused),
                    )
                    continue
            if self.embedder is not None:
                vector = await self.embedder(content)
                with self.database.transaction() as connection:
                    connection.execute(
                        "INSERT INTO retrieval_embeddings_staging VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            "knowledge", chunk_id, "", "", self.embedding_model,
                            len(vector), chunk_digest, pack_vector(vector), indexed_at,
                        ),
                    )
        return len(chunks)

    def remove_sources(self, source_ids: set[str]) -> None:
        with self.database.transaction() as connection:
            for source_id in source_ids:
                self._remove_source(connection, source_id)

    def verify(self) -> None:
        with self.database.connect() as connection:
            orphan_chunks = connection.execute(
                "SELECT count(*) FROM knowledge_chunks_staging c LEFT JOIN "
                "knowledge_sources_staging s ON s.source_id=c.source_id "
                "WHERE s.source_id IS NULL"
            ).fetchone()[0]
            orphan_vectors = connection.execute(
                "SELECT count(*) FROM retrieval_embeddings_staging e LEFT JOIN "
                "knowledge_chunks_staging c ON c.chunk_id=e.item_id "
                "WHERE e.source_kind='knowledge' AND c.chunk_id IS NULL"
            ).fetchone()[0]
            fts_count = connection.execute(
                "SELECT count(*) FROM knowledge_search_staging"
            ).fetchone()[0]
            chunk_count = connection.execute(
                "SELECT count(*) FROM knowledge_chunks_staging"
            ).fetchone()[0]
        if orphan_chunks or orphan_vectors or fts_count != chunk_count:
            raise RuntimeError("Knowledge staging integrity validation failed")

    def publish(self, connection) -> None:
        connection.execute("DELETE FROM retrieval_embeddings WHERE source_kind='knowledge'")
        connection.execute("DELETE FROM knowledge_search")
        connection.execute("DELETE FROM knowledge_chunks")
        connection.execute("DELETE FROM knowledge_sources")
        connection.execute("INSERT INTO knowledge_sources SELECT * FROM knowledge_sources_staging")
        connection.execute("INSERT INTO knowledge_chunks SELECT * FROM knowledge_chunks_staging")
        connection.execute(
            "INSERT INTO knowledge_search SELECT chunk_id,source_id,search_text "
            "FROM knowledge_search_staging"
        )
        connection.execute(
            "INSERT INTO retrieval_embeddings SELECT * FROM retrieval_embeddings_staging"
        )

    def clear(self) -> None:
        with self.database.transaction() as connection:
            self._clear(connection)

    @staticmethod
    def _remove_source(connection, source_id: str) -> None:
        chunk_ids = tuple(
            row[0] for row in connection.execute(
                "SELECT chunk_id FROM knowledge_chunks_staging WHERE source_id=?", (source_id,)
            )
        )
        for chunk_id in chunk_ids:
            connection.execute("DELETE FROM knowledge_search_staging WHERE chunk_id=?", (chunk_id,))
            connection.execute(
                "DELETE FROM retrieval_embeddings_staging WHERE source_kind='knowledge' AND item_id=?",
                (chunk_id,),
            )
        connection.execute("DELETE FROM knowledge_chunks_staging WHERE source_id=?", (source_id,))
        connection.execute("DELETE FROM knowledge_sources_staging WHERE source_id=?", (source_id,))

    @staticmethod
    def _clear(connection) -> None:
        connection.execute("DELETE FROM knowledge_search_staging")
        connection.execute("DELETE FROM retrieval_embeddings_staging")
        connection.execute("DELETE FROM knowledge_chunks_staging")
        connection.execute("DELETE FROM knowledge_sources_staging")
