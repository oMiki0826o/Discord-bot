"""tests/test_dmcc_nickname_sync.py

Modification():

- DMCC nickname sync: opt-in, bounded and permission-aware.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.mod.dmcc.repositories.links import JsonLinkRepository
from bot.mod.dmcc.services.nickname_sync import NicknameSyncConfig, NicknameSyncService

GUILD = "123456789012345678"
USER = "234567890123456789"


class Role:
    def __init__(self, position: int) -> None:
        self.position = position

    def __ge__(self, other: object) -> bool:
        return self.position >= other.position

    def __lt__(self, other: object) -> bool:
        return self.position < other.position


class Member:
    def __init__(self, guild: object, *, nickname: str | None = None) -> None:
        self.id = int(USER)
        self.guild = guild
        self.nick = nickname
        self.top_role = Role(1)
        self.bot = False
        self.edits: list[tuple[str | None, str]] = []

    async def edit(self, *, nick: str | None, reason: str) -> None:
        self.edits.append((nick, reason))
        self.nick = nick


def _fixture(tmp_path: Path, *, manage: bool = True, linked: bool = True):
    store = JsonLinkRepository(tmp_path / "links.json")
    if linked:
        store.link(USER, "123e4567-e89b-12d3-a456-426614174000", "Steve")
    guild = SimpleNamespace(id=int(GUILD), owner_id=999)
    guild.me = SimpleNamespace(
        guild_permissions=SimpleNamespace(manage_nicknames=manage), top_role=Role(5)
    )
    member = Member(guild)
    guild.get_member = lambda uid: member if uid == member.id else None
    guild.members = [member]
    bot = SimpleNamespace(get_guild=lambda gid: guild if gid == guild.id else None)
    return bot, guild, member, store


def _config(**options):
    return NicknameSyncConfig.from_mapping({
        "enabled": True,
        "guild_id": GUILD,
        "template": "[MC] {player_name}",
        **options,
    })


def test_config_rejects_unsafe_template_and_missing_guild() -> None:
    with pytest.raises(ValueError):
        NicknameSyncConfig.from_mapping({"enabled": True})
    for template in ("{player_name.__class__}", "{player_name:>30}", "", "{unknown}"):
        with pytest.raises(ValueError):
            _config(template=template)


def test_syncs_linked_member_only_and_skips_identical_value(tmp_path: Path) -> None:
    bot, _guild, member, store = _fixture(tmp_path)

    async def run():
        service = NicknameSyncService(bot, store, _config())
        assert await service.sync_user(USER)
        assert member.nick == "[MC] Steve"
        assert member.edits == [("[MC] Steve", "DMCC verified Minecraft account sync")]
        assert not await service.sync_user(USER)
        assert len(member.edits) == 1

    asyncio.run(run())


def test_unlinked_member_is_untouched_without_explicit_reset(tmp_path: Path) -> None:
    bot, _guild, member, store = _fixture(tmp_path, linked=False)
    member.nick = "My own nickname"

    async def run():
        service = NicknameSyncService(bot, store, _config())
        assert not await service.sync_user(USER)
        assert member.nick == "My own nickname"
        assert not member.edits

    asyncio.run(run())


def test_reset_unlinked_is_explicit_and_scoped(tmp_path: Path) -> None:
    bot, _guild, member, store = _fixture(tmp_path, linked=False)
    member.nick = "Other nickname"

    async def run():
        service = NicknameSyncService(bot, store, _config(reset_unlinked=True))
        assert await service.sync_user(USER)
        assert member.nick is None

    asyncio.run(run())


def test_no_edit_without_manage_nicknames_or_hierarchy(tmp_path: Path) -> None:
    bot, guild, member, store = _fixture(tmp_path, manage=False)

    async def run():
        service = NicknameSyncService(bot, store, _config())
        assert not await service.sync_user(USER)
        guild.me.guild_permissions.manage_nicknames = True
        member.top_role = Role(5)
        assert not await service.sync_user(USER)
        member.top_role = Role(1)
        guild.owner_id = member.id
        assert not await service.sync_user(USER)
        assert not member.edits

    asyncio.run(run())


def test_sweep_limits_per_cycle_and_does_not_touch_bots(tmp_path: Path) -> None:
    bot, _guild, member, store = _fixture(tmp_path)
    member.bot = True

    async def run():
        service = NicknameSyncService(bot, store, _config())
        assert await service.sweep_once() == 0
        assert not member.edits

    asyncio.run(run())


def test_sweep_rotates_members_instead_of_starving_later_users(tmp_path: Path) -> None:
    bot, guild, first, store = _fixture(tmp_path)
    second = Member(guild)
    second.id = 345678901234567890
    store.link(str(second.id), "123e4567-e89b-12d3-a456-426614174001", "Alex")
    guild.members = [first, second]

    async def run() -> None:
        service = NicknameSyncService(bot, store, _config(max_sweep_per_cycle=1))
        assert await service.sweep_once() == 1
        assert first.nick == "[MC] Steve"
        assert second.nick is None
        assert await service.sweep_once() == 1
        assert second.nick == "[MC] Alex"

    asyncio.run(run())
