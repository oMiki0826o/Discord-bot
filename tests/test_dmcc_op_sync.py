"""tests/test_dmcc_op_sync.py

Modification():

- Verify opt-in, permission-scoped server OP reconciliation without touching unknown players.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.mod.dmcc.repositories.links import JsonLinkRepository
from bot.mod.dmcc.services.op_sync import OpSyncConfig, OpSyncService
from bot.mod.dmcc.services.op_levels import OpLevelResolver


def _config(**overrides):
    return OpSyncConfig.from_mapping({
        "enabled": True,
        "guild_id": "123456789012345678",
        "interval_seconds": 600,
        "max_entries": 20,
        **overrides,
    })


def test_op_sync_settings_fail_closed():
    assert not OpSyncConfig.from_mapping({}).enabled
    for raw in (
        {"enabled": True},
        {"enabled": "yes", "guild_id": "123456789012345678"},
        {"enabled": True, "guild_id": "bad"},
        {"enabled": True, "guild_id": "123456789012345678", "max_entries": 0},
        {"enabled": True, "guild_id": "123456789012345678", "max_entries": 101},
        {"enabled": True, "guild_id": "123456789012345678", "allow_removals": "yes"},
    ):
        with pytest.raises(ValueError):
            OpSyncConfig.from_mapping(raw)


def test_reconcile_only_verified_guild_members_and_explicit_roles(tmp_path: Path):
    links = JsonLinkRepository(tmp_path / "links.json")
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    links.link("234567890123456789", uuid, "Steve")
    links.link("345678901234567890", "123e4567-e89b-12d3-a456-426614174001", "Alex")
    resolver = OpLevelResolver.from_mapping({
        "role_mappings": [{"role": "678901234567890123", "op_level": 2}],
    }, links)
    member = SimpleNamespace(id=234567890123456789, roles=[
        SimpleNamespace(id=678901234567890123, name="Trusted")
    ], display_name="Player")
    class Guild:
        def get_member(self, user_id):
            return member if user_id == member.id else None
    class Bot:
        def get_guild(self, guild_id):
            return Guild() if guild_id == 123456789012345678 else None
    class Manager:
        def all(self):
            return [SimpleNamespace(server_id="survival")]
    class Gateway:
        def __init__(self):
            self.sent = []
        async def send_packet(self, server_id, kind, req, data):
            self.sent.append((server_id, kind, req, data))

    async def run():
        gateway = Gateway()
        service = OpSyncService(_config(), Bot(), links, resolver, Manager(), gateway)
        assert await service.run_once()
        assert len(gateway.sent) == 1
        server, kind, request_id, data = gateway.sent[0]
        assert server == "survival" and kind == "op_sync_apply" and request_id is None
        assert data["entries"] == [{"minecraft_uuid": uuid, "minecraft_name": "Steve", "level": 2}]
        assert data["allow_removals"] is False
        await service.close()
    asyncio.run(run())


def test_missing_discord_member_never_causes_ops_revocation(tmp_path: Path):
    links = JsonLinkRepository(tmp_path / "links.json")
    links.link("234567890123456789", "123e4567-e89b-12d3-a456-426614174000", "Steve")
    class Bot:
        def get_guild(self, guild_id):
            return SimpleNamespace(get_member=lambda user_id: None)
    class Manager:
        def all(self):
            return [SimpleNamespace(server_id="survival")]
    class Gateway:
        async def send_packet(self, *args):
            raise AssertionError("No authoritative member info means no mutations")

    async def run():
        service = OpSyncService(
            _config(allow_removals=True), Bot(), links,
            OpLevelResolver.from_mapping({}, links), Manager(), Gateway(),
        )
        assert not await service.run_once()
    asyncio.run(run())


def test_op_sync_max_entries_matches_java_protocol_limit():
    assert _config(max_entries=100).max_entries == 100
    with pytest.raises(ValueError, match=r"1\.\.100"):
        _config(max_entries=101)


def test_op_sync_never_grants_operator_by_mutable_discord_names(tmp_path: Path):
    links = JsonLinkRepository(tmp_path / "links.json")
    links.link("234567890123456789", "123e4567-e89b-12d3-a456-426614174000", "Steve")
    resolver = OpLevelResolver.from_mapping({
        "user_mappings": [{"user": "ServerOwner", "op_level": 4}],
        "role_mappings": [{"role": "Admin", "op_level": 4}],
    }, links)
    member = SimpleNamespace(
        id=234567890123456789, name="ServerOwner",
        roles=[SimpleNamespace(id=678901234567890123, name="Admin")],
    )
    guild = SimpleNamespace(get_member=lambda _user_id: member)
    bot = SimpleNamespace(get_guild=lambda _guild_id: guild)
    manager = SimpleNamespace(all=lambda: [SimpleNamespace(server_id="survival")])

    class Gateway:
        def __init__(self):
            self.sent = []

        async def send_packet(self, *args):
            self.sent.append(args)

    async def run():
        gateway = Gateway()
        service = OpSyncService(_config(), bot, links, resolver, manager, gateway)
        assert not await service.run_once()
        assert gateway.sent == []

    asyncio.run(run())


def test_empty_authoritative_snapshot_revokes_orphaned_managed_ops(tmp_path: Path):
    links = JsonLinkRepository(tmp_path / "links.json")
    resolver = OpLevelResolver.from_mapping({}, links)
    guild = SimpleNamespace(chunked=True, get_member=lambda _id: None)
    bot = SimpleNamespace(get_guild=lambda _id: guild)
    manager = SimpleNamespace(all=lambda: [SimpleNamespace(server_id="survival")])
    class Gateway:
        def __init__(self):
            self.sent = []
        async def send_packet(self, *args):
            self.sent.append(args)
    async def run():
        gateway = Gateway()
        service = OpSyncService(_config(allow_removals=True), bot, links, resolver, manager, gateway)
        assert await service.run_once()
        assert gateway.sent == [(
            "survival", "op_sync_apply", None,
            {"entries": [], "allow_removals": True, "full_snapshot": True},
        )]
    asyncio.run(run())


def test_partial_guild_cache_cannot_authorize_full_op_reset(tmp_path: Path):
    links = JsonLinkRepository(tmp_path / "links.json")
    resolver = OpLevelResolver.from_mapping({}, links)
    guild = SimpleNamespace(chunked=False, get_member=lambda _id: None)
    bot = SimpleNamespace(get_guild=lambda _id: guild)
    manager = SimpleNamespace(all=lambda: [SimpleNamespace(server_id="survival")])
    class Gateway:
        async def send_packet(self, *args):
            raise AssertionError("partial member data cannot trigger OP removal")
    async def run():
        service = OpSyncService(_config(allow_removals=True), bot, links, resolver, manager, Gateway())
        assert not await service.run_once()
    asyncio.run(run())
