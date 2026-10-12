"""
bot/mod/ai/retrieval/vector.py

Modification():

- 建立 float32 BLOB 向量序列化、cosine similarity 與 scoped repository。

本檔案只保存可重建的 Embedding index，不作為原始資料。
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from ..database import AiDatabase


def pack_vector(values: tuple[float, ...]) -> bytes:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("vector must contain finite values")
    return struct.pack(f"<{len(values)}f", *values)


def unpack_vector(blob: bytes, *, dimensions: int) -> tuple[float, ...]:
    if len(blob) != dimensions * 4:
        raise ValueError("vector dimensions do not match blob")
    return tuple(struct.unpack(f"<{dimensions}f", blob))


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("vectors must have equal non-zero dimensions")
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return 0.0 if denominator == 0 else sum(a * b for a, b in zip(left, right, strict=True)) / denominator


@dataclass(frozen=True, slots=True)
class VectorRecord:
    source_kind: str
    item_id: str
    vector: tuple[float, ...]


class VectorRepository:
    def __init__(self, database: AiDatabase) -> None:
        self.database = database

    def upsert(self, *, source_kind: str, item_id: str, vector: tuple[float, ...], model: str, content_hash: str, now: int, user_id: str = "", channel_id: str = "") -> None:
        blob = pack_vector(vector)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO retrieval_embeddings (source_kind,item_id,scope_user_id,scope_channel_id,model,dimensions,content_hash,vector_blob,updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source_kind,item_id,model) DO UPDATE SET scope_user_id=excluded.scope_user_id,scope_channel_id=excluded.scope_channel_id,dimensions=excluded.dimensions,content_hash=excluded.content_hash,vector_blob=excluded.vector_blob,updated_at=excluded.updated_at",
                (source_kind, item_id, user_id, channel_id, model, len(vector), content_hash, blob, now),
            )

    def matches(self, *, source_kind: str, item_id: str, model: str, content_hash: str) -> bool:
        """Return whether an embedding already matches its content and model."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM retrieval_embeddings "
                "WHERE source_kind = ? AND item_id = ? AND model = ?",
                (source_kind, item_id, model),
            ).fetchone()
        return row is not None and str(row["content_hash"]) == content_hash

    def nearest(self, *, source_kind: str, query: tuple[float, ...], model: str, limit: int, user_id: str = "", channel_id: str = "") -> tuple[tuple[str, float], ...]:
        filters = ["source_kind = ?", "model = ?"]
        parameters: list[object] = [source_kind, model]
        if user_id:
            filters.append("scope_user_id = ?")
            parameters.append(user_id)
        if channel_id:
            filters.append("scope_channel_id = ?")
            parameters.append(channel_id)
        with self.database.connect() as connection:
            rows = connection.execute("SELECT item_id, dimensions, vector_blob FROM retrieval_embeddings WHERE " + " AND ".join(filters), parameters).fetchall()
        scored = [(str(row["item_id"]), cosine_similarity(query, unpack_vector(bytes(row["vector_blob"]), dimensions=int(row["dimensions"])))) for row in rows if int(row["dimensions"]) == len(query)]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return tuple(scored[:limit])
