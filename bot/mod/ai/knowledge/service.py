"""
bot/mod/ai/knowledge/service.py

Modification():

- 建立可重建、可增量更新的 Knowledge FTS5 index。
- 使用 Markdown-aware chunker 建立多個穩定內容識別碼。
- 重新索引時同步移除舊 chunk 的可重建 Embedding。

本檔案將原始文件視為 Source of Truth，SQLite 只保存可重建索引。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from opencc import OpenCC

from ..database import AiDatabase
from ..history.lexical import normalize_lexical_document, normalize_lexical_query
from .chunking import chunk_markdown


_CODE_QUERY_ALIASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("伺服器", "服务器"), "server"),
    (("啟動", "启动", "入口", "進入點", "进入点", "程式", "程序"), "main"),
    (("類別", "类"), "class"),
)

_TO_SIMPLIFIED = OpenCC("t2s")
_TO_TRADITIONAL = OpenCC("s2t")


def _query_forms(query: str) -> tuple[str, ...]:
    """Return deduplicated native, simplified, and traditional query forms."""

    return tuple(dict.fromkeys(
        value for value in (query, _TO_SIMPLIFIED.convert(query), _TO_TRADITIONAL.convert(query))
        if value.strip()
    ))


def _knowledge_match_queries(query: str) -> tuple[str, ...]:
    """Return strict FTS queries across Traditional/Simplified Chinese forms."""

    primaries = [normalize_lexical_query(value) for value in _query_forms(query)]
    aliases = [
        replacement
        for terms, replacement in _CODE_QUERY_ALIASES
        if any(term in query for term in terms)
    ]
    lowered = query.casefold()
    if "server" in lowered:
        aliases.append("server")
    if any(term in lowered for term in ("startup", "entry point", "entrypoint")):
        aliases.append("main")
    aliases = list(dict.fromkeys(aliases))
    if aliases:
        primaries.append(normalize_lexical_query(" ".join(aliases)))
    return tuple(dict.fromkeys(primaries))


def _relaxed_match_queries(query: str) -> tuple[str, ...]:
    """Fallback for CJK terms split by markup or punctuation in source text.

    FTS5's default AND semantics require every generated CJK bigram.  A source
    such as ``更新 抑制`` therefore cannot match a user query ``更新抑制``.
    The relaxed form keeps all lexical terms but lets BM25 rank their union.
    """

    queries = []
    for value in _query_forms(query):
        tokens = tuple(dict.fromkeys(normalize_lexical_document(value).split()))
        if tokens:
            queries.append(" OR ".join(tokens))
    return tuple(dict.fromkeys(queries))


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    source_id: str
    title: str
    content: str
    origin: str


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_id: str
    source_id: str
    content: str


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    chunk: KnowledgeChunk
    score: float
    title: str = ""
    title_match: int = 0


def _title_match_score(query: str, title: str) -> int:
    """Score direct article-title mentions across Chinese script variants.

    Article titles are owner-controlled metadata and are much less noisy than
    a full-text hit in a long changelog.  This deliberately stays generic: it
    does not contain Minecraft entity aliases or one-off query fixes.
    """

    title_parts = tuple(
        part.strip()
        for part in re.split(r"[/|｜:：]+", title)
        if part.strip()
    )
    title_forms = tuple(dict.fromkeys(
        form
        for part in (title, *title_parts)
        for form in _query_forms(part)
    ))
    query_forms = _query_forms(query)
    return max(
        (len(title_form) for title_form in title_forms
         if len(title_form.strip()) >= 2
         and any(title_form.casefold() in query_form.casefold() for query_form in query_forms)),
        default=0,
    )


class KnowledgeService:
    def __init__(self, database: AiDatabase, *, chunk_chars: int = 2_000) -> None:
        if chunk_chars < 32:
            raise ValueError("chunk_chars must be at least 32")
        self.database = database
        self.chunk_chars = chunk_chars

    def index(self, document: KnowledgeDocument, *, now: int) -> tuple[str, ...]:
        if not all(value.strip() for value in (document.source_id, document.title, document.content, document.origin)):
            raise ValueError("Knowledge document fields must not be blank")
        digest = hashlib.sha256(document.content.encode()).hexdigest()
        chunks = chunk_markdown(document.content, max_chars=self.chunk_chars)
        with self.database.transaction() as connection:
            existing = connection.execute("SELECT content_hash FROM knowledge_sources WHERE source_id = ?", (document.source_id,)).fetchone()
            if existing is not None and str(existing["content_hash"]) == digest:
                rows = connection.execute("SELECT chunk_id FROM knowledge_chunks WHERE source_id = ? ORDER BY ordinal", (document.source_id,)).fetchall()
                return tuple(str(row["chunk_id"]) for row in rows)
            occurrences: dict[str, int] = {}
            prepared_chunks: list[tuple[str, int, str, str]] = []
            for ordinal, content in enumerate(chunks):
                chunk_digest = hashlib.sha256(content.encode()).hexdigest()
                occurrence = occurrences.get(chunk_digest, 0)
                occurrences[chunk_digest] = occurrence + 1
                chunk_id = "knowledge_" + hashlib.sha256(
                    f"{document.source_id}:{chunk_digest}:{occurrence}".encode()
                ).hexdigest()[:24]
                prepared_chunks.append((chunk_id, ordinal, content, chunk_digest))
            retained_ids = {item[0] for item in prepared_chunks}
            old_ids = [str(row["chunk_id"]) for row in connection.execute("SELECT chunk_id FROM knowledge_chunks WHERE source_id = ?", (document.source_id,))]
            for old_id in old_ids:
                connection.execute("DELETE FROM knowledge_search WHERE chunk_id = ?", (old_id,))
                if old_id not in retained_ids:
                    connection.execute(
                        "DELETE FROM retrieval_embeddings WHERE source_kind = 'knowledge' AND item_id = ?",
                        (old_id,),
                    )
            connection.execute("DELETE FROM knowledge_chunks WHERE source_id = ?", (document.source_id,))
            connection.execute(
                "INSERT INTO knowledge_sources (source_id, title, origin, content_hash, indexed_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET title=excluded.title, origin=excluded.origin, content_hash=excluded.content_hash, indexed_at=excluded.indexed_at",
                (document.source_id, document.title, document.origin, digest, now),
            )
            chunk_ids: list[str] = []
            for chunk_id, ordinal, content, chunk_digest in prepared_chunks:
                connection.execute(
                    "INSERT INTO knowledge_chunks (chunk_id, source_id, ordinal, content, content_hash) VALUES (?, ?, ?, ?, ?)",
                    (chunk_id, document.source_id, ordinal, content, chunk_digest),
                )
                connection.execute(
                    "INSERT INTO knowledge_search (chunk_id, source_id, search_text) VALUES (?, ?, ?)",
                    (chunk_id, document.source_id, normalize_lexical_document(document.title + "\n" + content)),
                )
                chunk_ids.append(chunk_id)
        return tuple(chunk_ids)

    def remove_sources_not_in(self, source_ids: set[str]) -> int:
        """在完整重建時移除已刪除原稿留下的衍生資料。"""

        with self.database.transaction() as connection:
            rows = connection.execute("SELECT source_id FROM knowledge_sources").fetchall()
            obsolete_ids = [str(row["source_id"]) for row in rows if str(row["source_id"]) not in source_ids]
            for source_id in obsolete_ids:
                chunk_ids = [str(row["chunk_id"]) for row in connection.execute(
                    "SELECT chunk_id FROM knowledge_chunks WHERE source_id = ?", (source_id,)
                )]
                for chunk_id in chunk_ids:
                    connection.execute("DELETE FROM knowledge_search WHERE chunk_id = ?", (chunk_id,))
                    connection.execute(
                        "DELETE FROM retrieval_embeddings WHERE source_kind = 'knowledge' AND item_id = ?",
                        (chunk_id,),
                    )
                connection.execute("DELETE FROM knowledge_sources WHERE source_id = ?", (source_id,))
        return len(obsolete_ids)

    def search(self, query: str, *, limit: int) -> tuple[KnowledgeHit, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self.database.connect() as connection:
            best_rows = {}
            # Run strict and relaxed forms together.  A strict hit can be a
            # changelog or quoted user sentence containing every filler word;
            # it must not prevent a concise article-title match from entering
            # the candidate set.
            match_queries = tuple(dict.fromkeys((
                *_knowledge_match_queries(query),
                *_relaxed_match_queries(query),
            )))
            candidate_limit = max(20, limit * 4)
            for match_query in match_queries:
                rows = connection.execute(
                    "SELECT c.*, s.title, bm25(knowledge_search) AS rank "
                    "FROM knowledge_search "
                    "JOIN knowledge_chunks c ON c.chunk_id = knowledge_search.chunk_id "
                    "JOIN knowledge_sources s ON s.source_id = c.source_id "
                    "WHERE knowledge_search MATCH ? ORDER BY rank, c.chunk_id LIMIT ?",
                    (match_query, candidate_limit),
                ).fetchall()
                for row in rows:
                    chunk_id = str(row["chunk_id"])
                    if chunk_id not in best_rows or float(row["rank"]) < float(best_rows[chunk_id]["rank"]):
                        best_rows[chunk_id] = row
        rows = sorted(
            best_rows.values(),
            key=lambda row: (
                -_title_match_score(query, str(row["title"])),
                float(row["rank"]),
                str(row["chunk_id"]),
            ),
        )[:limit]
        return tuple(KnowledgeHit(
            KnowledgeChunk(str(row["chunk_id"]), str(row["source_id"]), str(row["content"])),
            -float(row["rank"]),
            str(row["title"]),
            _title_match_score(query, str(row["title"])),
        ) for row in rows)

    def read_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM knowledge_chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return None if row is None else KnowledgeChunk(str(row["chunk_id"]), str(row["source_id"]), str(row["content"]))

    def read_verified_chunk(self, chunk_id: str, *, source_reader: object) -> KnowledgeChunk | None:
        """回讀原稿並驗證 hash；索引過期或來源不見時不回傳舊 SQLite 內容。"""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT c.chunk_id, c.source_id, c.ordinal, s.content_hash "
                "FROM knowledge_chunks c JOIN knowledge_sources s ON s.source_id = c.source_id "
                "WHERE c.chunk_id = ?",
                (chunk_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            document = source_reader.read(str(row["source_id"]))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        digest = hashlib.sha256(document.content.encode()).hexdigest()
        if digest != str(row["content_hash"]):
            return None
        chunks = chunk_markdown(document.content, max_chars=self.chunk_chars)
        ordinal = int(row["ordinal"])
        if ordinal >= len(chunks):
            return None
        return KnowledgeChunk(str(row["chunk_id"]), str(row["source_id"]), chunks[ordinal])
