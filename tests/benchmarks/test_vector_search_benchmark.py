"""tests/benchmarks/test_vector_search_benchmark.py

Modification():

- 提供 1k、10k、50k SQLite 向量全表搜尋的可重複手動基準。

此檔不定義 pytest 測試，避免日常 CI 執行效能量測。
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.retrieval.vector import VectorRepository, pack_vector


def benchmark(size: int, dimensions: int) -> float:
    """Build ``size`` deterministic vectors and return query latency in ms."""

    with tempfile.TemporaryDirectory(prefix="discord-bot-vector-benchmark-") as directory:
        database = AiDatabase(Path(directory) / "ai.sqlite3")
        database.initialize()
        vector = tuple(1.0 if index == 0 else 0.0 for index in range(dimensions))
        blob = pack_vector(vector)
        rows = [
            ("knowledge", f"chunk-{index}", "", "", "benchmark", dimensions, str(index), blob, index)
            for index in range(size)
        ]
        with database.transaction() as connection:
            connection.executemany(
                "INSERT INTO retrieval_embeddings "
                "(source_kind,item_id,scope_user_id,scope_channel_id,model,dimensions,content_hash,vector_blob,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
        repository = VectorRepository(database)
        started = time.perf_counter()
        repository.nearest(source_kind="knowledge", query=vector, model="benchmark", limit=10)
        return (time.perf_counter() - started) * 1_000


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark SQLite vector full-scan latency.")
    parser.add_argument("--sizes", nargs="+", type=int, default=(1_000, 10_000, 50_000))
    parser.add_argument("--dimensions", type=int, default=16)
    arguments = parser.parse_args()
    for size in arguments.sizes:
        print(f"vectors={size} latency_ms={benchmark(size, arguments.dimensions):.2f}")


if __name__ == "__main__":
    main()
