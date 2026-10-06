"""
tests/test_ai_migration_operations.py

Modification():

- Legacy AI migration has a read-only inspection boundary before apply.
- 維護 test ai migration operations 的發布版行為與驗證契約。
"""

import sqlite3

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.migration import LegacyMigrator


def test_legacy_ai_inspect_reports_without_creating_target(tmp_path) -> None:
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE messages (id INTEGER, user_id TEXT, role TEXT, content TEXT, channel_id TEXT, created_at REAL)")
        connection.execute("CREATE TABLE memories (id INTEGER, user_id TEXT, scope_type TEXT, channel_id TEXT, keyword TEXT, category TEXT, content TEXT, importance INTEGER, confidence REAL, status TEXT, source_message_id INTEGER, created_at REAL)")
        connection.execute("INSERT INTO messages VALUES (1, 'user-a', 'user', 'hello', 'chan', 1)")
        connection.execute("INSERT INTO memories VALUES (1, 'user-a', 'channel', 'chan', 'pref', 'preference', 'likes tea', 3, 1, 'active', 1, 1)")
    target = AiDatabase(tmp_path / "target.db")

    report = LegacyMigrator(legacy, target).inspect()

    assert report.events_imported == 1
    assert report.memories_imported == 1
    assert not target.path.exists()
