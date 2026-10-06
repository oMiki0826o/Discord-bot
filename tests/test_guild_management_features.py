"""
tests/test_guild_management_features.py

Modification():

- 提供 test guild management features 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

from bot.mod.guild.database import GuildDatabase
from bot.mod.guild.command import ServerSettingsSelect
from bot.mod.guild.stats.model import StatChannel, StatMetric
from bot.mod.guild.stats.repository import GuildStatsRepository
from bot.mod.guild.stats.service import GuildStatsService


def test_guild_database_migrates_legacy_settings_without_data_loss(tmp_path) -> None:
    path = tmp_path / "guild.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE guild_settings (guild_id INTEGER PRIMARY KEY, "
        "welcome_channel_id INTEGER NOT NULL DEFAULT 0, leave_channel_id INTEGER NOT NULL DEFAULT 0, "
        "log_channel_id INTEGER NOT NULL DEFAULT 0, auto_role_id INTEGER NOT NULL DEFAULT 0, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.execute("INSERT INTO guild_settings (guild_id, welcome_channel_id) VALUES (1, 22)")
    connection.commit()
    connection.close()

    database = GuildDatabase(path)

    assert database.get_settings(1).welcome_channel_id == 22
    with database._connect() as current:
        assert current.execute("PRAGMA user_version").fetchone()[0] >= 4


def test_stats_repository_crud_and_role_validation(tmp_path) -> None:
    database = GuildDatabase(tmp_path / "guild.db")
    repository = GuildStatsRepository(database)
    value = StatChannel(1, 10, StatMetric.MEMBER_TOTAL, "成員：{count}")
    repository.upsert(value)
    assert repository.list_for_guild(1) == (value,)

    try:
        repository.upsert(StatChannel(1, 11, StatMetric.ROLE_MEMBERS, "VIP：{count}"))
    except ValueError as exc:
        assert "role_id" in str(exc)
    else:
        raise AssertionError("role_members without role_id was accepted")

    repository.delete(1, 10)
    assert repository.list_for_guild(1) == ()


class FakeVoiceChannel:
    def __init__(self, channel_id: int, name: str) -> None:
        self.id = channel_id
        self.name = name
        self.edits = []

    async def edit(self, *, name: str, reason: str) -> None:
        self.name = name
        self.edits.append((name, reason))


def test_stats_service_only_renames_when_value_changes(tmp_path) -> None:
    database = GuildDatabase(tmp_path / "guild.db")
    repository = GuildStatsRepository(database)
    repository.upsert(StatChannel(1, 10, StatMetric.HUMAN_TOTAL, "人類：{count}"))
    channel = FakeVoiceChannel(10, "舊名稱")
    guild = SimpleNamespace(
        id=1,
        members=[SimpleNamespace(bot=False), SimpleNamespace(bot=False), SimpleNamespace(bot=True)],
        member_count=3,
        get_channel=lambda channel_id: channel if channel_id == 10 else None,
        get_role=lambda _role_id: None,
    )
    service = GuildStatsService(repository, minimum_rename_interval_seconds=0)

    first = asyncio.run(service.refresh_guild(guild, force=True))
    second = asyncio.run(service.refresh_guild(guild, force=True))

    assert first.updated == 1
    assert second.unchanged == 1
    assert channel.edits == [("人類：2", "更新伺服器統計頻道")]


def test_online_metric_refuses_to_guess_without_presence_intent(tmp_path) -> None:
    database = GuildDatabase(tmp_path / "guild.db")
    repository = GuildStatsRepository(database)
    repository.upsert(StatChannel(1, 10, StatMetric.ONLINE_TOTAL, "在線：{count}"))
    channel = FakeVoiceChannel(10, "舊名稱")
    guild = SimpleNamespace(
        id=1,
        members=[SimpleNamespace(bot=False, status="online")],
        member_count=1,
        get_channel=lambda _channel_id: channel,
        get_role=lambda _role_id: None,
        _state=SimpleNamespace(_intents=SimpleNamespace(presences=False)),
    )

    report = asyncio.run(GuildStatsService(repository, minimum_rename_interval_seconds=0).refresh_guild(guild, force=True))

    assert report.failed == 1
    assert channel.edits == []
    assert "Presence Intent" in repository.list_for_guild(1)[0].last_error


def test_server_settings_panel_exposes_stats_and_announcements() -> None:
    select = ServerSettingsSelect(SimpleNamespace())
    values = {option.value for option in select.options}
    assert {"stats", "announcement"} <= values
