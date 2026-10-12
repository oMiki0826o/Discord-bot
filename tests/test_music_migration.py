"""
tests/test_music_migration.py

Modification():

- Legacy music favourites migrate only through an explicit, idempotent operation.
- 維護 test music migration 的發布版行為與驗證契約。
"""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

from bot.mod.music.database import MusicDatabase
from bot.mod.music.migration import LegacyFavoritesMigrator
from bot.mod.music.player import GuildPlayer
from bot.mod.music.song import Song
from pathlib import Path


def _legacy(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE music_favorites (user_id TEXT, title TEXT, url TEXT, duration INTEGER, added_at REAL)")
        connection.execute("INSERT INTO music_favorites VALUES ('user-a', 'Song', 'https://example.test/song', 123, 42)")


def test_music_migration_dry_run_does_not_write_and_apply_preserves_timestamp(tmp_path) -> None:
    legacy = tmp_path / "legacy.db"
    _legacy(legacy)
    target = MusicDatabase(tmp_path / "music.db")
    migration = LegacyFavoritesMigrator(legacy, target)

    assert migration.dry_run().insertable == 1
    assert migration.apply().inserted == 1
    assert target._get_favorites("user-a")[0]["added_at"] == 42
    assert migration.apply().duplicates == 1


def test_play_command_keeps_search_for_single_song_mode() -> None:
    source = (Path(__file__).resolve().parents[1] / "bot/mod/music/command.py").read_text(encoding="utf-8")

    assert 'if mode == "playlist" and not is_youtube_url(url):' in source


def test_play_next_skips_many_unplayable_songs_without_recursion(monkeypatch) -> None:
    async def run() -> None:
        player = GuildPlayer(SimpleNamespace(), SimpleNamespace(name="guild"))
        player._vc = SimpleNamespace(is_connected=lambda: True)
        monkeypatch.setattr(player, "_delete_now_playing_message", lambda *_args: asyncio.sleep(0))
        attempts = 0

        async def cannot_start(_song) -> bool:
            nonlocal attempts
            attempts += 1
            return False

        monkeypatch.setattr(player, "_start_song", cannot_start)
        monkeypatch.setattr(player, "_start_idle_timer", lambda: None)
        for index in range(1100):
            player.queue._queue.append(Song(
                title=str(index), webpage_url="https://example.test", uploader="",
                duration=1, thumbnail=None, requester=SimpleNamespace(),
            ))

        await player._play_next()

        assert attempts == 1100
        assert player.queue.current is None

    asyncio.run(run())
