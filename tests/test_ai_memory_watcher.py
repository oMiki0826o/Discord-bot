"""
tests/test_ai_memory_watcher.py

Modification():

- 驗證 Memory Mirror Watcher 以兩次相同雜湊防抖。
- 驗證本程式自寫鏡像不會被重新套用。
- 驗證檔案刪除會在防抖後撤銷對應 Active Memory。
"""

from __future__ import annotations

import asyncio
import json

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.memory.mirror import MemoryMirrorService
from bot.mod.ai.memory.models import (
    AssertionStrength,
    MemoryCandidate,
    MemoryScopeType,
    TemporalScope,
)
from bot.mod.ai.memory.repository import MemoryRepository
from bot.mod.ai.memory.watcher import MemoryMirrorWatcher

USER_ID = "123456789012345678"


def _seed(database: AiDatabase) -> None:
    repository = MemoryRepository(database)
    candidate = MemoryCandidate(
        "candidate",
        "event",
        USER_ID,
        MemoryScopeType.GLOBAL,
        USER_ID,
        "preference",
        "drink",
        "tea",
        1.0,
        4,
        AssertionStrength.EXPLICIT,
        TemporalScope.PERMANENT,
        1,
    )
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO events (
                event_id, user_id, channel_id, conversation_id,
                role, content, created_at
            ) VALUES ('event', ?, 'channel', 'conversation', 'user', 'tea', 1)
            """,
            (USER_ID,),
        )
        repository.add(candidate, connection)


def test_watcher_debounces_owner_edit_and_ignores_own_export(tmp_path) -> None:
    async def scenario() -> None:
        database = AiDatabase(tmp_path / "ai.db")
        database.initialize()
        _seed(database)
        mirror = MemoryMirrorService(database, tmp_path / "auto_memory", clock=lambda: 10)
        path = mirror.export_user(USER_ID)
        watcher = MemoryMirrorWatcher(mirror, tmp_path / "auto_memory", interval=1)

        assert await watcher.scan_once() == 0

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["memories"][0]["value"] = "coffee"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        assert await watcher.scan_once() == 0
        assert await watcher.scan_once() == 1
        assert await watcher.scan_once() == 0

        with database.connect() as connection:
            rows = connection.execute(
                "SELECT value_json FROM memories WHERE user_id = ? AND status = 'active'",
                (USER_ID,),
            ).fetchall()
        assert [json.loads(row["value_json"]) for row in rows] == ["coffee"]

    asyncio.run(scenario())


def test_watcher_debounces_file_deletion_before_retracting_all(tmp_path) -> None:
    async def scenario() -> None:
        database = AiDatabase(tmp_path / "ai.db")
        database.initialize()
        _seed(database)
        mirror = MemoryMirrorService(database, tmp_path / "auto_memory", clock=lambda: 10)
        path = mirror.export_user(USER_ID)
        watcher = MemoryMirrorWatcher(mirror, tmp_path / "auto_memory", interval=1)
        assert await watcher.scan_once() == 0

        path.unlink()
        assert await watcher.scan_once() == 0
        assert await watcher.scan_once() == 1

        with database.connect() as connection:
            assert connection.execute(
                "SELECT count(*) FROM memories WHERE user_id = ? AND status = 'active'",
                (USER_ID,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT count(*) FROM memory_owner_overrides WHERE user_id = ?",
                (USER_ID,),
            ).fetchone()[0] == 1

    asyncio.run(scenario())
