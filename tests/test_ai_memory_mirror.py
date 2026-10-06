"""
tests/test_ai_memory_mirror.py

Modification():

- 驗證 Owner 撤銷保留 Evidence 並封鎖同 identity 的模型候選。
- 驗證 Owner JSON 新增、修改、刪除會建立版本而非覆寫歷史。
- 驗證非法 JSON、user_id/檔名不一致與舊 memory_id 不污染 SQLite。
- 驗證舊版 Memory status CHECK migration 可安全升級為 retracted。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.memory.consolidator import MemoryConsolidator
from bot.mod.ai.memory.mirror import MemoryMirrorService
from bot.mod.ai.memory.models import (
    AssertionStrength,
    CandidateStatus,
    MemoryCandidate,
    MemoryScopeType,
    TemporalScope,
)
from bot.mod.ai.memory.policy import ConflictResolver
from bot.mod.ai.memory.repository import MemoryRepository

USER_ID = "123456789012345678"


def _candidate(
    candidate_id: str,
    event_id: str,
    *,
    key: str = "drink",
    value: object = "tea",
    scope_type: MemoryScopeType = MemoryScopeType.GLOBAL,
    scope_id: str = USER_ID,
    observed_at: int = 1,
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id,
        event_id,
        USER_ID,
        scope_type,
        scope_id,
        "preference",
        key,
        value,
        1.0,
        4,
        AssertionStrength.EXPLICIT,
        TemporalScope.PERMANENT,
        observed_at,
    )


def _insert_event(database: AiDatabase, event_id: str, *, created_at: int = 1) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO events (
                event_id, user_id, channel_id, conversation_id,
                role, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, USER_ID, "channel", "conversation", "user", event_id, created_at),
        )


def _active_rows(database: AiDatabase):
    with database.connect() as connection:
        return connection.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ? AND status = 'active'
            ORDER BY memory_key
            """,
            (USER_ID,),
        ).fetchall()


def test_retract_preserves_evidence_and_blocks_only_the_same_key_scope(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    repository = MemoryRepository(database)
    candidate = _candidate("candidate", "event")
    _insert_event(database, "event")

    with database.transaction() as connection:
        memory = repository.add(candidate, connection)
        repository.retract(
            memory.memory_id,
            actor_id="owner",
            now=2,
            connection=connection,
        )

        assert connection.execute(
            "SELECT count(*) FROM memory_evidence WHERE memory_id = ?",
            (memory.memory_id,),
        ).fetchone()[0] == 1
        assert repository.is_owner_blocked(candidate, connection)
        other_scope = _candidate(
            "other",
            "event",
            scope_type=MemoryScopeType.CHANNEL,
            scope_id="channel",
        )
        assert not repository.is_owner_blocked(other_scope, connection)

    assert repository.get(memory.memory_id).status.value == "retracted"


def test_owner_retracted_key_rejects_future_model_candidate(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    repository = MemoryRepository(database)
    first = _candidate("candidate-1", "event-1")
    _insert_event(database, "event-1", created_at=1)

    with database.transaction() as connection:
        memory = repository.add(first, connection)
        repository.retract(
            memory.memory_id,
            actor_id="owner",
            now=2,
            connection=connection,
        )

    _insert_event(database, "event-2", created_at=3)
    second = _candidate(
        "candidate-2",
        "event-2",
        value="coffee",
        observed_at=3,
    )
    consolidator = MemoryConsolidator(
        database=database,
        repository=repository,
        resolver=ConflictResolver(),
    )

    result = consolidator.consolidate(second)

    assert result.memory is None
    assert result.reason == "owner_retracted"
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, result_reason FROM memory_candidates WHERE candidate_id = ?",
            (second.candidate_id,),
        ).fetchone()
        assert row["status"] == CandidateStatus.REJECTED.value
        assert row["result_reason"] == "owner_retracted"
        assert connection.execute(
            "SELECT count(*) FROM memories WHERE user_id = ? AND status = 'active'",
            (USER_ID,),
        ).fetchone()[0] == 0


def test_owner_json_edit_creates_versions_and_retraction_block(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    repository = MemoryRepository(database)
    candidate = _candidate("candidate", "event")
    _insert_event(database, "event")
    with database.transaction() as connection:
        original = repository.add(candidate, connection)

    mirror = MemoryMirrorService(database, tmp_path / "auto_memory", clock=lambda: 10)
    path = mirror.export_user(USER_ID, "Miki")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["memories"][0]["value"] = "coffee"
    payload["memories"][0]["importance"] = 5
    payload["memories"].append(
        {
            "scope_type": "global",
            "scope_id": USER_ID,
            "memory_type": "preference",
            "memory_key": "language",
            "value": "zh-TW",
            "importance": 4,
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = mirror.apply_path(path)

    assert (report.updated, report.added, report.retracted) == (1, 1, 0)
    assert repository.get(original.memory_id).status.value == "superseded"
    active = _active_rows(database)
    assert [row["memory_key"] for row in active] == ["drink", "language"]
    assert json.loads(active[0]["value_json"]) == "coffee"
    assert active[0]["memory_id"] != original.memory_id

    normalized = json.loads(path.read_text(encoding="utf-8"))
    removed = next(item for item in normalized["memories"] if item["memory_key"] == "drink")
    normalized["memories"] = [
        item for item in normalized["memories"] if item["memory_key"] != "drink"
    ]
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = mirror.apply_path(path)

    assert report.retracted == 1
    with database.connect() as connection:
        assert connection.execute(
            "SELECT status FROM memories WHERE memory_id = ?",
            (removed["memory_id"],),
        ).fetchone()[0] == "retracted"
        assert connection.execute(
            "SELECT count(*) FROM memory_owner_overrides WHERE memory_key = 'drink'"
        ).fetchone()[0] == 1


def test_owner_can_readd_retracted_identity_and_clear_block(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    repository = MemoryRepository(database)
    candidate = _candidate("candidate", "event")
    _insert_event(database, "event")
    with database.transaction() as connection:
        memory = repository.add(candidate, connection)
        repository.retract(memory.memory_id, actor_id="owner", now=2, connection=connection)

    mirror = MemoryMirrorService(database, tmp_path / "auto_memory", clock=lambda: 3)
    path = mirror.export_user(USER_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["memories"].append(
        {
            "scope_type": "global",
            "scope_id": USER_ID,
            "memory_type": "preference",
            "memory_key": "drink",
            "value": "water",
            "importance": 5,
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = mirror.apply_path(path)

    assert report.added == 1
    assert repository.owner_block_count() == 0
    active = _active_rows(database)
    assert len(active) == 1
    assert json.loads(active[0]["value_json"]) == "water"
    assert active[0]["memory_id"] != memory.memory_id


def test_invalid_or_mismatched_mirror_does_not_modify_sqlite(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    repository = MemoryRepository(database)
    candidate = _candidate("candidate", "event")
    _insert_event(database, "event")
    with database.transaction() as connection:
        repository.add(candidate, connection)

    mirror = MemoryMirrorService(database, tmp_path / "auto_memory")
    path = mirror.export_user(USER_ID, "Miki")
    before = [(row["memory_id"], row["value_json"], row["status"]) for row in _active_rows(database)]

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["user_id"] = "999999999999999999"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="檔名 user_id"):
        mirror.apply_path(path)

    after = [(row["memory_id"], row["value_json"], row["status"]) for row in _active_rows(database)]
    assert after == before



def test_mirror_filename_requires_discord_snowflake(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    mirror = MemoryMirrorService(database, tmp_path / "auto_memory")
    path = tmp_path / "auto_memory" / "Miki(not-a-user-id).json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": 1, "user_id": "not-a-user-id", "memories": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="檔名 user_id"):
        mirror.apply_path(path)

def test_schema_v13_upgrades_legacy_memory_status_without_losing_rows(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        );
        CREATE TABLE memories (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK (scope_type IN ('global', 'channel', 'conversation')),
            scope_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            memory_key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
            importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
            status TEXT NOT NULL CHECK (status IN ('active', 'uncertain', 'superseded', 'expired', 'rejected')),
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            last_confirmed_at INTEGER,
            expires_at INTEGER,
            superseded_by_id TEXT REFERENCES memories(memory_id) ON DELETE RESTRICT
        );
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY
        );
        CREATE TABLE memory_candidates (
            candidate_id TEXT PRIMARY KEY
        );
        CREATE TABLE memory_evidence (
            memory_id TEXT NOT NULL REFERENCES memories(memory_id) ON DELETE CASCADE,
            event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
            candidate_id TEXT NOT NULL REFERENCES memory_candidates(candidate_id) ON DELETE CASCADE,
            relation TEXT NOT NULL CHECK (relation IN ('supporting', 'contradicting')),
            created_at INTEGER NOT NULL,
            PRIMARY KEY (memory_id, event_id, candidate_id, relation)
        );
        INSERT INTO memories VALUES (
            'mem-1', '123456789012345678', 'global', '123456789012345678',
            'preference', 'drink', '"tea"', 1.0, 4, 'active', 1, 1, 1, NULL, NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 1)",
        [(version,) for version in range(1, 13)],
    )
    connection.commit()
    connection.close()

    database = AiDatabase(path)
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            "UPDATE memories SET status = 'retracted' WHERE memory_id = 'mem-1'"
        )
        assert connection.execute(
            "SELECT status FROM memories WHERE memory_id = 'mem-1'"
        ).fetchone()[0] == "retracted"
        assert connection.execute(
            "SELECT max(version) FROM schema_migrations"
        ).fetchone()[0] == 13
