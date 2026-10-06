"""
tests/test_ai_manual_data.py

Modification():

- 提供 test ai manual data 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import json

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.memory.manual_sync import ManualMemorySyncService


def test_manual_memory_validate_and_preview_do_not_write_sources_or_database(tmp_path) -> None:
    root = tmp_path / "users_memory"
    root.mkdir()
    source = root / "Lucky(12345678901234567).json"
    source.write_text(json.dumps({
        "user_id": "12345678901234567",
        "memories": [{"content": "likes tea"}],
    }), encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    service = ManualMemorySyncService(database, root)

    assert service.validate().records == 1
    assert service.preview().records == 1
    assert '"id"' not in source.read_text(encoding="utf-8")
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM manual_memory_records").fetchone()[0] == 0
