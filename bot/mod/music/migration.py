"""
bot/mod/music/migration.py

Modification():

- Explicit, read-only legacy favourite migration for the Music module。
- 展開遷移計數與略過分支，避免壓縮敘述影響可讀性。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .database import MusicDatabase


@dataclass(frozen=True, slots=True)
class FavoritesMigrationReport:
    scanned: int
    insertable: int
    inserted: int
    duplicates: int
    invalid: int


class LegacyFavoritesMigrator:
    def __init__(self, legacy_path: Path, target: MusicDatabase) -> None:
        self.legacy_path = Path(legacy_path)
        self.target = target

    def dry_run(self) -> FavoritesMigrationReport:
        return self._run(apply=False)

    def apply(self) -> FavoritesMigrationReport:
        return self._run(apply=True)

    def _run(self, *, apply: bool) -> FavoritesMigrationReport:
        if not self.legacy_path.is_file():
            raise FileNotFoundError(self.legacy_path)
        source = sqlite3.connect(f"file:{self.legacy_path}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        try:
            columns = {str(row["name"]) for row in source.execute("PRAGMA table_info(music_favorites)")}
            required = {"user_id", "title", "url", "duration", "added_at"}
            if required - columns:
                raise ValueError("legacy music_favorites schema is incomplete")
            rows = source.execute("SELECT user_id, title, url, duration, added_at FROM music_favorites ORDER BY rowid").fetchall()
        finally:
            source.close()
        scanned = len(rows)
        insertable = inserted = duplicates = invalid = 0
        with self.target._connect() as destination:
            for row in rows:
                user_id, title, url = (str(row[key] or "").strip() for key in ("user_id", "title", "url"))
                if not user_id or not title or not url.startswith(("http://", "https://")):
                    invalid += 1
                    continue
                exists = destination.execute("SELECT 1 FROM music_favorites WHERE user_id = ? AND url = ?", (user_id, url)).fetchone()
                if exists:
                    duplicates += 1
                    continue
                insertable += 1
                if apply:
                    destination.execute("INSERT INTO music_favorites (user_id, title, url, duration, added_at) VALUES (?, ?, ?, ?, ?)", (user_id, title, url, max(0, int(row["duration"] or 0)), float(row["added_at"] or 0)))
                    inserted += 1
        return FavoritesMigrationReport(scanned, insertable, inserted, duplicates, invalid)
