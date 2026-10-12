"""
bot/mod/ai/database.py

Modification():

- 建立 AI Module 專用 SQLite Connection。
- 管理短生命週期 Transaction。
- 建立 Event、Memory Candidate、Memory、Owner override 與 Evidence Schema。
- 以 migration 修復舊版 Memory status 約束，保留既有記憶與 Evidence。

本檔負責 AI Module Database 基礎設施與 Migration。
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import AiDatabaseBusyError


# ── Schema ──────────────────────

_MIGRATION_1: tuple[str, ...] = (
    """
    CREATE TABLE events (
        event_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        message_id TEXT,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
        content TEXT NOT NULL CHECK (length(trim(content)) > 0),
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE (channel_id, message_id)
    )
    """,
    """
    CREATE INDEX idx_events_scope_time
    ON events(user_id, channel_id, conversation_id, created_at, event_id)
    """,
    """
    CREATE TABLE memory_candidates (
        candidate_id TEXT PRIMARY KEY,
        source_event_id TEXT NOT NULL
            REFERENCES events(event_id) ON DELETE RESTRICT,
        user_id TEXT NOT NULL,
        scope_type TEXT NOT NULL
            CHECK (scope_type IN ('global', 'channel', 'conversation')),
        scope_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        memory_key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        confidence REAL NOT NULL
            CHECK (confidence >= 0.0 AND confidence <= 1.0),
        importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
        assertion_strength TEXT NOT NULL
            CHECK (assertion_strength IN ('tentative', 'observed', 'explicit')),
        temporal_scope TEXT NOT NULL
            CHECK (temporal_scope IN ('temporary', 'ongoing', 'permanent')),
        status TEXT NOT NULL
            CHECK (status IN ('pending', 'accepted', 'ignored', 'conflict', 'rejected')),
        observed_at INTEGER NOT NULL CHECK (observed_at >= 0),
        decided_at INTEGER,
        result_action TEXT,
        result_reason TEXT,
        result_memory_id TEXT
    )
    """,
    """
    CREATE TABLE memories (
        memory_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        scope_type TEXT NOT NULL
            CHECK (scope_type IN ('global', 'channel', 'conversation')),
        scope_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        memory_key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        confidence REAL NOT NULL
            CHECK (confidence >= 0.0 AND confidence <= 1.0),
        importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
        status TEXT NOT NULL
            CHECK (status IN ('active', 'uncertain', 'superseded', 'expired', 'rejected', 'retracted')),
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        last_confirmed_at INTEGER,
        expires_at INTEGER,
        superseded_by_id TEXT
            REFERENCES memories(memory_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE UNIQUE INDEX idx_memories_one_active_key
    ON memories(user_id, scope_type, scope_id, memory_type, memory_key)
    WHERE status = 'active'
    """,
    """
    CREATE INDEX idx_memories_active_scope
    ON memories(user_id, scope_type, scope_id, status, importance, updated_at)
    """,
    """
    CREATE TABLE memory_evidence (
        memory_id TEXT NOT NULL
            REFERENCES memories(memory_id) ON DELETE CASCADE,
        event_id TEXT NOT NULL
            REFERENCES events(event_id) ON DELETE RESTRICT,
        candidate_id TEXT NOT NULL
            REFERENCES memory_candidates(candidate_id) ON DELETE RESTRICT,
        relation TEXT NOT NULL
            CHECK (relation IN ('supporting', 'contradicting')),
        created_at INTEGER NOT NULL,
        PRIMARY KEY (memory_id, event_id, candidate_id, relation)
    )
    """,
)

_MIGRATION_2: tuple[str, ...] = (
    """
    CREATE VIRTUAL TABLE event_search USING fts5(
        event_id UNINDEXED,
        user_id UNINDEXED,
        channel_id UNINDEXED,
        conversation_id UNINDEXED,
        role UNINDEXED,
        created_at UNINDEXED,
        search_text,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TABLE topic_states (
        topic_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        scope_type TEXT NOT NULL
            CHECK (scope_type IN ('global', 'channel', 'conversation')),
        scope_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL
            CHECK (status IN ('active', 'paused', 'completed', 'archived')),
        current_goal TEXT,
        state_json TEXT NOT NULL DEFAULT '{}',
        version INTEGER NOT NULL CHECK (version >= 1),
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        updated_at INTEGER NOT NULL CHECK (updated_at >= created_at),
        UNIQUE (user_id, scope_type, scope_id, name)
    )
    """,
    """
    CREATE INDEX idx_topic_states_scope
    ON topic_states(user_id, scope_type, scope_id, status, updated_at)
    """,
    """
    CREATE TABLE topic_evidence (
        topic_id TEXT NOT NULL
            REFERENCES topic_states(topic_id) ON DELETE CASCADE,
        event_id TEXT NOT NULL
            REFERENCES events(event_id) ON DELETE RESTRICT,
        version INTEGER NOT NULL CHECK (version >= 1),
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        PRIMARY KEY (topic_id, event_id, version)
    )
    """,
)

_MIGRATION_3: tuple[str, ...] = (
    """
    CREATE TABLE memory_jobs (
        job_id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL UNIQUE
            REFERENCES events(event_id) ON DELETE CASCADE,
        status TEXT NOT NULL
            CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        available_at INTEGER NOT NULL CHECK (available_at >= 0),
        last_error TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        updated_at INTEGER NOT NULL CHECK (updated_at >= 0)
    )
    """,
    """
    CREATE INDEX idx_memory_jobs_ready
    ON memory_jobs(status, available_at, created_at)
    """,
    """
    CREATE TABLE public_profiles (
        user_id TEXT NOT NULL,
        profile_key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL CHECK (updated_at >= 0),
        PRIMARY KEY (user_id, profile_key)
    )
    """,
    """
    CREATE TABLE knowledge_sources (
        source_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        origin TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        indexed_at INTEGER NOT NULL CHECK (indexed_at >= 0)
    )
    """,
    """
    CREATE TABLE knowledge_chunks (
        chunk_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL
            REFERENCES knowledge_sources(source_id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        UNIQUE (source_id, ordinal)
    )
    """,
    """
    CREATE VIRTUAL TABLE knowledge_search USING fts5(
        chunk_id UNINDEXED,
        source_id UNINDEXED,
        search_text,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """,
)

_MIGRATION_4: tuple[str, ...] = (
    """
    CREATE TABLE retrieval_embeddings (
        source_kind TEXT NOT NULL,
        item_id TEXT NOT NULL,
        scope_user_id TEXT NOT NULL DEFAULT '',
        scope_channel_id TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        dimensions INTEGER NOT NULL CHECK (dimensions > 0),
        content_hash TEXT NOT NULL,
        vector_blob BLOB NOT NULL,
        updated_at INTEGER NOT NULL CHECK (updated_at >= 0),
        PRIMARY KEY (source_kind, item_id, model)
    )
    """,
    """
    CREATE INDEX idx_retrieval_embeddings_scope
    ON retrieval_embeddings(source_kind, scope_user_id, scope_channel_id)
    """,
)

_MIGRATION_5: tuple[str, ...] = (
    """CREATE TABLE manual_memory_records (
        memory_id TEXT PRIMARY KEY, source_path TEXT NOT NULL, user_id TEXT NOT NULL,
        memory_key TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL,
        importance INTEGER NOT NULL, confidence REAL NOT NULL, source TEXT NOT NULL,
        updated_at TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL
    )""",
    """CREATE VIRTUAL TABLE manual_memory_search USING fts5(
        memory_id UNINDEXED, user_id UNINDEXED, search_text,
        tokenize = 'unicode61 remove_diacritics 2'
    )""",
)

_MIGRATION_6: tuple[str, ...] = (
    """CREATE TABLE ai_access_rules (
        user_id TEXT PRIMARY KEY,
        state TEXT NOT NULL CHECK (state IN ('banned', 'restricted')),
        reason TEXT NOT NULL DEFAULT '', actor_id TEXT NOT NULL,
        expires_at INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )""",
    """CREATE TABLE ai_operation_audit (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id TEXT NOT NULL, action TEXT NOT NULL, target_id TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
    )""",
)

_MIGRATION_7: tuple[str, ...] = (
    """CREATE TABLE conversation_summaries (
        conversation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
        first_event_id TEXT NOT NULL, last_event_id TEXT NOT NULL,
        source_hash TEXT NOT NULL, content TEXT NOT NULL,
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )""",
)

_MIGRATION_8: tuple[str, ...] = (
    """CREATE TABLE search_cache (
        query TEXT PRIMARY KEY,
        text TEXT NOT NULL,
        stable INTEGER NOT NULL CHECK (stable IN (0, 1)),
        expires_at INTEGER NOT NULL
    )""",
    """CREATE INDEX idx_search_cache_expires_at
    ON search_cache(expires_at)""",
    """CREATE TABLE ai_usage (
        usage_id INTEGER PRIMARY KEY,
        user_id TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
        output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
        created_at INTEGER NOT NULL
    )""",
    """CREATE INDEX idx_ai_usage_created_at ON ai_usage(created_at)""",
    """CREATE TABLE ai_provider_errors (
        error_id INTEGER PRIMARY KEY,
        user_id TEXT NOT NULL,
        model TEXT NOT NULL,
        error_type TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    """CREATE INDEX idx_ai_provider_errors_created_at
    ON ai_provider_errors(created_at)""",
)

_MIGRATION_9: tuple[str, ...] = (
    """CREATE TABLE ai_data_manifest (
        source_path TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL,
        source_type TEXT NOT NULL,
        applied_at INTEGER NOT NULL
    )""",
)

_MIGRATION_10: tuple[str, ...] = (
    """CREATE TABLE ai_user_state (
        user_id TEXT PRIMARY KEY,
        tier INTEGER NOT NULL DEFAULT 0 CHECK (tier BETWEEN 0 AND 3),
        interaction_count INTEGER NOT NULL DEFAULT 0 CHECK (interaction_count >= 0),
        mode TEXT NOT NULL DEFAULT 'normal',
        mode_expires_at INTEGER,
        updated_at INTEGER NOT NULL
    )""",
)

_MIGRATION_11: tuple[str, ...] = (
    """CREATE TABLE ai_provider_traces (
        trace_id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        model TEXT NOT NULL,
        outcome TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    """CREATE INDEX idx_ai_provider_traces_request
    ON ai_provider_traces(request_id, trace_id)""",
)

_MIGRATION_12: tuple[str, ...] = (
    """CREATE TABLE memory_owner_overrides (
        user_id TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
        memory_type TEXT NOT NULL, memory_key TEXT NOT NULL, actor_id TEXT NOT NULL,
        created_at INTEGER NOT NULL, PRIMARY KEY (user_id, scope_type, scope_id, memory_type, memory_key)
    )""",
    """CREATE TABLE memory_owner_audit (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL,
        actor_id TEXT NOT NULL, action TEXT NOT NULL, created_at INTEGER NOT NULL
    )""",
)

_MIGRATION_14: tuple[str, ...] = (
    """CREATE TABLE ai_data_sync_state (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        status TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        updated_at INTEGER NOT NULL
    )""",
    """INSERT INTO ai_data_sync_state (singleton, status, detail, updated_at)
    VALUES (1, 'idle', '', 0)""",
)

_MIGRATION_15: tuple[str, ...] = (
    "ALTER TABLE ai_data_sync_state ADD COLUMN operation_id TEXT NOT NULL DEFAULT ''",
)

_MIGRATION_16: tuple[str, ...] = (
    "ALTER TABLE ai_usage ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0)",
    "ALTER TABLE ai_usage ADD COLUMN thinking_tokens INTEGER NOT NULL DEFAULT 0 CHECK (thinking_tokens >= 0)",
    "ALTER TABLE ai_usage ADD COLUMN estimated INTEGER NOT NULL DEFAULT 1 CHECK (estimated IN (0, 1))",
    "UPDATE ai_usage SET total_tokens = input_tokens + output_tokens WHERE total_tokens = 0",
)


# ── Database ──────────────────────

class AiDatabase:
    """管理 AI Module 自己的 SQLite Database。"""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms 不得小於 0")

        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self) -> sqlite3.Connection:
        """建立單次操作使用的 SQLite Connection。"""

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            f"PRAGMA busy_timeout = {self.busy_timeout_ms}"
        )
        return connection

    @contextmanager
    def transaction(
        self,
    ) -> Iterator[sqlite3.Connection]:
        """建立短生命週期寫入 Transaction。"""

        connection: sqlite3.Connection | None = None

        try:
            connection = self.connect()
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()

        except sqlite3.OperationalError as exc:
            if connection is not None:
                connection.rollback()

            if "locked" in str(exc).lower():
                raise AiDatabaseBusyError(
                    "AI Database 正在忙碌，請稍後重試"
                ) from exc

            raise

        except Exception:
            if connection is not None:
                connection.rollback()
            raise

        finally:
            if connection is not None:
                connection.close()

    def initialize(self) -> None:
        """套用尚未執行的 AI Database Migration。"""

        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at INTEGER NOT NULL
                )
                """
            )

            applied = {
                int(row["version"])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                )
            }

            if 1 not in applied:
                for statement in _MIGRATION_1:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (?, ?)",
                    (1, int(time.time())),
                )

            if 2 not in applied:
                self._apply_migration_2(connection)

            if 3 not in applied:
                for statement in _MIGRATION_3:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (3, int(time.time())),
                )

            if 4 not in applied:
                for statement in _MIGRATION_4:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (4, int(time.time())),
                )
            if 5 not in applied:
                for statement in _MIGRATION_5:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (5, int(time.time())))
            if 6 not in applied:
                for statement in _MIGRATION_6:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (6, int(time.time())))
            if 7 not in applied:
                for statement in _MIGRATION_7:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (7, int(time.time())))
            if 8 not in applied:
                for statement in _MIGRATION_8:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (8, int(time.time())))
            if 9 not in applied:
                for statement in _MIGRATION_9:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (9, int(time.time())))
            if 10 not in applied:
                for statement in _MIGRATION_10:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (10, int(time.time())))
            if 11 not in applied:
                for statement in _MIGRATION_11:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (11, int(time.time())))
            if 12 not in applied:
                for statement in _MIGRATION_12:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (12, int(time.time())),
                )

            if 13 not in applied:
                self._apply_migration_13(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (13, int(time.time())),
                )
            if 14 not in applied:
                for statement in _MIGRATION_14:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (14, int(time.time())),
                )
            if 15 not in applied:
                for statement in _MIGRATION_15:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (15, int(time.time())),
                )
            if 16 not in applied:
                for statement in _MIGRATION_16:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (16, int(time.time())),
                )

    @staticmethod
    def _apply_migration_13(connection: sqlite3.Connection) -> None:
        """Allow ``retracted`` memories on databases created before schema v12."""

        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'memories'"
        ).fetchone()
        schema_sql = "" if row is None or row["sql"] is None else str(row["sql"])
        if "'retracted'" in schema_sql:
            return

        # Rebuild both the parent table and its evidence child inside the same
        # transaction so legacy installations keep every memory/evidence row.
        connection.execute(
            """
            CREATE TABLE memories_v13 (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                scope_type TEXT NOT NULL
                    CHECK (scope_type IN ('global', 'channel', 'conversation')),
                scope_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                confidence REAL NOT NULL
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
                importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
                status TEXT NOT NULL
                    CHECK (status IN ('active', 'uncertain', 'superseded', 'expired', 'rejected', 'retracted')),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                last_confirmed_at INTEGER,
                expires_at INTEGER,
                superseded_by_id TEXT
                    REFERENCES memories_v13(memory_id) ON DELETE RESTRICT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memories_v13 (
                memory_id, user_id, scope_type, scope_id, memory_type, memory_key,
                value_json, confidence, importance, status, created_at, updated_at,
                last_confirmed_at, expires_at, superseded_by_id
            )
            SELECT
                memory_id, user_id, scope_type, scope_id, memory_type, memory_key,
                value_json, confidence, importance, status, created_at, updated_at,
                last_confirmed_at, expires_at, superseded_by_id
            FROM memories
            """
        )
        connection.execute(
            """
            CREATE TABLE memory_evidence_v13 (
                memory_id TEXT NOT NULL
                    REFERENCES memories_v13(memory_id) ON DELETE CASCADE,
                event_id TEXT NOT NULL
                    REFERENCES events(event_id) ON DELETE RESTRICT,
                candidate_id TEXT NOT NULL
                    REFERENCES memory_candidates(candidate_id) ON DELETE RESTRICT,
                relation TEXT NOT NULL
                    CHECK (relation IN ('supporting', 'contradicting')),
                created_at INTEGER NOT NULL,
                PRIMARY KEY (memory_id, event_id, candidate_id, relation)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_evidence_v13 (
                memory_id, event_id, candidate_id, relation, created_at
            )
            SELECT memory_id, event_id, candidate_id, relation, created_at
            FROM memory_evidence
            """
        )
        connection.execute("DROP TABLE memory_evidence")
        connection.execute("DROP TABLE memories")
        connection.execute("ALTER TABLE memories_v13 RENAME TO memories")
        connection.execute("ALTER TABLE memory_evidence_v13 RENAME TO memory_evidence")
        connection.execute(
            """
            CREATE UNIQUE INDEX idx_memories_one_active_key
            ON memories(user_id, scope_type, scope_id, memory_type, memory_key)
            WHERE status = 'active'
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_memories_active_scope
            ON memories(user_id, scope_type, scope_id, status, importance, updated_at)
            """
        )

    @staticmethod
    def _apply_migration_2(
        connection: sqlite3.Connection,
    ) -> None:
        from .history.lexical import normalize_lexical_document

        candidate_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(memory_candidates)"
            )
        }
        if "result_memory_json" not in candidate_columns:
            connection.execute(
                "ALTER TABLE memory_candidates "
                "ADD COLUMN result_memory_json TEXT"
            )

        for statement in _MIGRATION_2:
            connection.execute(statement)

        rows = connection.execute(
            "SELECT event_id, user_id, channel_id, conversation_id, "
            "role, created_at, content FROM events"
        ).fetchall()
        for row in rows:
            connection.execute(
                "INSERT INTO event_search ("
                "event_id, user_id, channel_id, conversation_id, role, "
                "created_at, search_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row["event_id"],
                    row["user_id"],
                    row["channel_id"],
                    row["conversation_id"],
                    row["role"],
                    row["created_at"],
                    normalize_lexical_document(str(row["content"])),
                ),
            )

        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (2, int(time.time())),
        )
