"""
bot/mod/ai/memory/manual_sync.py

Modification():

- Owner-managed JSON memory normalization and SQLite retrieval projection。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..database import AiDatabase
from ..history.lexical import normalize_lexical_document, normalize_lexical_query

_NAME = re.compile(r"^.+\((?P<user_id>\d{17,20})\)\.json$")


@dataclass(frozen=True, slots=True)
class ManualSyncReport:
    records: int


class ManualMemorySyncService:
    def __init__(self, database: AiDatabase, root: Path, *, clock=lambda: datetime.now().astimezone()) -> None:
        self.database = database
        self.root = Path(root)
        self.clock = clock

    def sync(self) -> ManualSyncReport:
        documents = self._prepare_documents()
        rows = []
        for path, user_id, document in documents:
            rows.extend(self._rows(path, user_id, document))
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM manual_memory_search")
            connection.execute("DELETE FROM manual_memory_records")
            for row in rows:
                connection.execute(
                    "INSERT INTO manual_memory_records (memory_id, source_path, user_id, memory_key, category, content, importance, confidence, source, updated_at, version, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row,
                )
                connection.execute(
                    "INSERT INTO manual_memory_search (memory_id, user_id, search_text) VALUES (?, ?, ?)",
                    (row[0], row[2], normalize_lexical_document(f"{row[3]} {row[4]} {row[5]}")),
                )
        return ManualSyncReport(len(rows))

    def validate(self) -> ManualSyncReport:
        """Validate and normalize in memory only; no source or SQLite writes."""
        documents = self._prepare_documents()
        return ManualSyncReport(sum(len(document["memories"]) for _path, _user_id, document in documents))

    def preview(self) -> ManualSyncReport:
        """Return the pending normalized record count without applying it."""
        return self.validate()

    def seed_staging(self) -> None:
        """Seed a replacement dataset from active rows without parsing source files."""

        with self.database.transaction() as connection:
            connection.execute("DELETE FROM manual_memory_search_staging")
            connection.execute("DELETE FROM manual_memory_records_staging")
            connection.execute("INSERT INTO manual_memory_records_staging SELECT * FROM manual_memory_records")
            connection.execute(
                "INSERT INTO manual_memory_search_staging "
                "SELECT memory_id,user_id,search_text FROM manual_memory_search"
            )

    def stage_changed(self, relative_paths: tuple[str, ...], removed_paths: tuple[str, ...]) -> int:
        """Parse only changed manual JSON files and update their staging projection."""

        changed_names = {Path(path).name for path in relative_paths if path.startswith("users_memory/")}
        removed_names = {Path(path).name for path in removed_paths if path.startswith("users_memory/")}
        total = 0
        with self.database.transaction() as connection:
            for name in sorted(changed_names | removed_names):
                ids = tuple(
                    row[0] for row in connection.execute(
                        "SELECT memory_id FROM manual_memory_records_staging WHERE source_path=?",
                        (name,),
                    )
                )
                for memory_id in ids:
                    connection.execute(
                        "DELETE FROM manual_memory_search_staging WHERE memory_id=?", (memory_id,)
                    )
                connection.execute(
                    "DELETE FROM manual_memory_records_staging WHERE source_path=?", (name,)
                )

        for name in sorted(changed_names):
            path = self.root / name
            documents = self._prepare_path(path)
            rows = self._rows(*documents)
            total += len(rows)
            with self.database.transaction() as connection:
                for row in rows:
                    connection.execute(
                        "INSERT INTO manual_memory_records_staging VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        row,
                    )
                    connection.execute(
                        "INSERT INTO manual_memory_search_staging (memory_id,user_id,search_text) "
                        "VALUES (?,?,?)",
                        (row[0], row[2], normalize_lexical_document(f"{row[3]} {row[4]} {row[5]}")),
                    )
        return total

    def publish_staging(self, connection) -> None:
        connection.execute("DELETE FROM manual_memory_search")
        connection.execute("DELETE FROM manual_memory_records")
        connection.execute("INSERT INTO manual_memory_records SELECT * FROM manual_memory_records_staging")
        connection.execute(
            "INSERT INTO manual_memory_search SELECT memory_id,user_id,search_text "
            "FROM manual_memory_search_staging"
        )

    def clear_staging(self) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM manual_memory_search_staging")
            connection.execute("DELETE FROM manual_memory_records_staging")

    def _prepare_documents(self) -> list[tuple[Path, str, dict]]:
        now = self.clock().isoformat(timespec="seconds")
        documents: list[tuple[Path, str, dict]] = []
        for path in sorted(self.root.glob("*.json")) if self.root.is_dir() else ():
            match = _NAME.fullmatch(path.name)
            if match is None:
                raise ValueError(f"invalid user memory filename: {path.name}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            user_id = match.group("user_id")
            if not isinstance(payload, dict) or payload.get("user_id") != user_id:
                raise ValueError(f"user_id does not match filename: {path.name}")
            normalized = self._normalize(payload, now=now)
            documents.append((path, user_id, normalized))
        return documents

    def _prepare_path(self, path: Path) -> tuple[Path, str, dict]:
        match = _NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"invalid user memory filename: {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        user_id = match.group("user_id")
        if not isinstance(payload, dict) or payload.get("user_id") != user_id:
            raise ValueError(f"user_id does not match filename: {path.name}")
        return path, user_id, self._normalize(payload, now=self.clock().isoformat(timespec="seconds"))

    @staticmethod
    def _rows(path: Path, user_id: str, document: dict) -> list[tuple[object, ...]]:
        return [
            (
                item["id"], path.name, user_id, item["key"], item["category"], item["content"],
                item["importance"], item["confidence"], item["source"], item["updated_at"], item["version"],
                hashlib.sha256(item["content"].encode()).hexdigest(),
            )
            for item in document["memories"]
        ]

    def search(self, user_id: str, query: str, *, limit: int) -> tuple[dict[str, object], ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT r.* FROM manual_memory_search s JOIN manual_memory_records r ON r.memory_id = s.memory_id WHERE s.user_id = ? AND manual_memory_search MATCH ? ORDER BY bm25(manual_memory_search), r.importance DESC LIMIT ?",
                (user_id, normalize_lexical_query(query), limit),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    @staticmethod
    def _normalize(payload: dict, *, now: str) -> dict:
        preferences = payload.get("preferences", {})
        memories = list(payload.get("memories", []))
        if not isinstance(preferences, dict) or not isinstance(memories, list):
            raise ValueError("preferences must be object and memories must be array")
        for key, value in preferences.items():
            text = f"使用者偏好{key}：{value if not isinstance(value, list) else '、'.join(map(str, value))}"
            memories.append({"key": f"preference.{key}", "category": "preference", "content": text, "importance": 4})
        normalized = []
        for index, item in enumerate(memories):
            if not isinstance(item, dict) or not isinstance(item.get("content"), str) or not item["content"].strip():
                raise ValueError("memory content must not be blank")
            key = str(item.get("key") or "general." + hashlib.sha256(item["content"].casefold().encode()).hexdigest()[:16]).casefold()
            importance = item.get("importance", 3)
            if not isinstance(importance, int) or isinstance(importance, bool) or not 1 <= importance <= 5:
                raise ValueError("importance must be 1..5")
            category = str(item.get("category") or key.split(".", 1)[0])
            content = item["content"].strip()
            stable_identity = json.dumps(
                [payload["user_id"], index, key, category, content],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            normalized.append({
                "id": str(item.get("id") or "manual-" + hashlib.sha256(stable_identity.encode()).hexdigest()[:32]), "key": key,
                "category": category, "content": content,
                "importance": importance, "source": "manual", "updated_at": str(item.get("updated_at") or now),
                "confidence": 1.0, "version": int(item.get("version") or 1),
            })
        return {"user_id": payload["user_id"], "preferences": preferences, "memories": normalized}
