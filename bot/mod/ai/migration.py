"""
bot/mod/ai/migration.py

Modification():

- 建立只讀取舊 SQLite、驗證後寫入新 schema 的一次性 migration。
- 只搬有 user message evidence 的 active memory，無法追溯者明確略過。

本檔案不屬於正式 Runtime fallback，不修改舊資料庫。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .database import AiDatabase
from .history.models import EventRole, NewEvent
from .history.repository import EventRepository
from .memory.models import AssertionStrength, MemoryCandidate, MemoryScopeType, TemporalScope
from .memory.repository import MemoryRepository
from .memory.service import MemoryService

_NAME = re.compile(r"[^a-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class MigrationReport:
    events_imported: int
    memories_imported: int
    memories_skipped: int


class LegacyMigrator:
    def __init__(self, legacy_path: Path, target: AiDatabase) -> None:
        self.legacy_path = Path(legacy_path)
        self.target = target

    def run(self) -> MigrationReport:
        if not self.legacy_path.is_file():
            raise FileNotFoundError(self.legacy_path)
        self.target.initialize()
        events = EventRepository(self.target)
        memory = MemoryService(database=self.target, event_repository=events, memory_repository=MemoryRepository(self.target))
        source = sqlite3.connect(f"file:{self.legacy_path}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        try:
            self._require_columns(source, "messages", {"id", "user_id", "role", "content", "channel_id", "created_at"})
            self._require_columns(source, "memories", {"id", "user_id", "scope_type", "channel_id", "keyword", "category", "content", "importance", "confidence", "status", "source_message_id", "created_at"})
            imported_events: dict[int, object] = {}
            for row in source.execute("SELECT * FROM messages ORDER BY id"):
                if str(row["role"]) not in {"user", "assistant"} or not str(row["content"]).strip():
                    continue
                message_id = int(row["id"])
                event = events.append(NewEvent(
                    event_id=f"legacy-message-{message_id}", user_id=str(row["user_id"]),
                    channel_id=str(row["channel_id"] or "legacy"), message_id=f"legacy-{message_id}",
                    conversation_id=f"legacy:{row['user_id']}:{row['channel_id'] or 'legacy'}",
                    role=EventRole(str(row["role"])), content=str(row["content"]),
                    created_at=max(0, int(float(row["created_at"]))), metadata={"migration": "legacy"},
                ))
                imported_events[message_id] = event
            imported_memories = 0
            skipped = 0
            for row in source.execute("SELECT * FROM memories WHERE status = 'active' ORDER BY id"):
                source_id = row["source_message_id"]
                event = imported_events.get(int(source_id)) if source_id is not None else None
                if event is None or event.role is not EventRole.USER or event.user_id != str(row["user_id"]):
                    skipped += 1
                    continue
                candidate = MemoryCandidate(
                    candidate_id=f"legacy-candidate-{row['id']}", source_event_id=event.event_id,
                    user_id=event.user_id, scope_type=MemoryScopeType.CHANNEL,
                    scope_id=event.channel_id, memory_type=self._name(str(row["category"]), "general"),
                    memory_key=self._name(str(row["keyword"]), f"memory_{row['id']}"),
                    value=str(row["content"]), confidence=min(1.0, max(0.0, float(row["confidence"]))),
                    importance=min(5, max(1, int(row["importance"]))), assertion_strength=AssertionStrength.OBSERVED,
                    temporal_scope=TemporalScope.ONGOING, observed_at=event.created_at,
                )
                memory.consolidate(candidate)
                imported_memories += 1
            return MigrationReport(len(imported_events), imported_memories, skipped)
        finally:
            source.close()

    def inspect(self) -> MigrationReport:
        """Read legacy rows and validate migratable evidence without touching target."""
        if not self.legacy_path.is_file():
            raise FileNotFoundError(self.legacy_path)
        source = sqlite3.connect(f"file:{self.legacy_path}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        try:
            self._require_columns(source, "messages", {"id", "user_id", "role", "content", "channel_id", "created_at"})
            self._require_columns(source, "memories", {"id", "user_id", "status", "source_message_id"})
            events = {
                int(row["id"]): str(row["user_id"])
                for row in source.execute("SELECT id, user_id, role, content FROM messages")
                if str(row["role"]) in {"user", "assistant"} and str(row["content"]).strip()
            }
            valid_users = {
                int(row["id"]): str(row["user_id"])
                for row in source.execute("SELECT id, user_id, role, content FROM messages")
                if str(row["role"]) == "user" and str(row["content"]).strip()
            }
            imported = skipped = 0
            for row in source.execute("SELECT user_id, status, source_message_id FROM memories"):
                source_id = row["source_message_id"]
                if str(row["status"]) == "active" and source_id is not None and valid_users.get(int(source_id)) == str(row["user_id"]):
                    imported += 1
                elif str(row["status"]) == "active":
                    skipped += 1
            return MigrationReport(len(events), imported, skipped)
        finally:
            source.close()

    @staticmethod
    def _require_columns(connection: sqlite3.Connection, table: str, required: set[str]) -> None:
        columns = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}
        missing = required - columns
        if missing:
            raise ValueError(f"Legacy {table} missing columns: {', '.join(sorted(missing))}")

    @staticmethod
    def _name(value: str, fallback: str) -> str:
        normalized = _NAME.sub("_", value.casefold()).strip("_.-")
        if not normalized or not normalized[0].isalpha():
            normalized = fallback
        return normalized[:80]
