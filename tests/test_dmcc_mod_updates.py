"""tests/test_dmcc_mod_updates.py

Modification():

- Assert opt-in, authenticated Fabric inventory, Modrinth version checking, and deduped notifications.

"""
from __future__ import annotations

import asyncio

import pytest

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.mod_updates import ModUpdateConfig, ModUpdateService


class Sender:
    def __init__(self):
        self.messages = []

    async def send_discord_message(self, channel_id, content):
        self.messages.append((channel_id, content))


def _config():
    return ModUpdateConfig.from_mapping({
        "enabled": True,
        "interval_seconds": 3600,
        "servers": {"survival": {
            "channel_id": "123456789012345678",
            "minecraft_version": "1.21.8",
            "projects": {"lithium": "gvQqBUqZ"},
        }},
    }, {"survival"})


def test_mod_update_config_rejects_invalid_project_and_server():
    with pytest.raises(ValueError):
        ModUpdateConfig.from_mapping({"enabled": "yes"}, {"survival"})
    with pytest.raises(ValueError):
        ModUpdateConfig.from_mapping({"servers": {"unknown": {}}}, {"survival"})
    with pytest.raises(ValueError):
        ModUpdateConfig.from_mapping({"servers": {"survival": {
            "channel_id": "123456789012345678", "minecraft_version": "1.21.8",
            "projects": {"lithium": "https://evil.example/path"},
        }}}, {"survival"})


def test_mod_update_notifies_only_newer_compatible_versions():
    async def scenario():
        calls = []
        async def fetch(project, minecraft_version):
            calls.append((project, minecraft_version))
            return [
                {"version_number": "0.13.1", "game_versions": ["1.21.8"], "loaders": ["fabric"]},
                {"version_number": "0.13.0", "game_versions": ["1.21.8"], "loaders": ["fabric"]},
                {"version_number": "0.12.0", "game_versions": ["1.21.8"], "loaders": ["fabric"]},
            ]
        sender = Sender()
        service = ModUpdateService(_config(), sender, fetch_versions=fetch)
        await service.on_event(MinecraftEvent("server_started", "survival", {
            "minecraft_version": "1.21.8", "mods": [{"mod_id": "lithium", "version": "0.13.0"}],
        }))
        await service.run_once()
        assert calls == [("gvQqBUqZ", "1.21.8")]
        assert len(sender.messages) == 1
        assert "lithium" in sender.messages[0][1]
        assert "0.13.1" in sender.messages[0][1]
        await service.run_once()
        assert len(sender.messages) == 1

    asyncio.run(scenario())


def test_mod_update_never_announces_unknown_or_incompatible_installed_versions():
    async def scenario():
        async def fetch(project, version):
            return [{"version_number": "2.0", "game_versions": ["1.21.8"], "loaders": ["fabric"]}]
        sender = Sender()
        service = ModUpdateService(_config(), sender, fetch_versions=fetch)
        await service.on_event(MinecraftEvent("server_started", "survival", {
            "minecraft_version": "1.21.8", "mods": [{"mod_id": "lithium", "version": "custom"}],
        }))
        await service.run_once()
        assert sender.messages == []
        await service.on_event(MinecraftEvent("server_started", "survival", {
            "minecraft_version": "1.21.9", "mods": [{"mod_id": "lithium", "version": "1.0"}],
        }))
        await service.run_once()
        assert sender.messages == []

    asyncio.run(scenario())


def test_mod_update_skips_cached_inventory_when_bridge_disconnects():
    async def scenario():
        calls = []
        class Manager:
            connected = True
            def get(self, server_id):
                return object() if self.connected else None

        manager = Manager()
        async def fetch(project, version):
            calls.append(project)
            return [
                {"version_number": "1.1.0", "game_versions": ["1.21.8"], "loaders": ["fabric"]},
                {"version_number": "1.0.0", "game_versions": ["1.21.8"], "loaders": ["fabric"]},
            ]
        sender = Sender()
        service = ModUpdateService(_config(), sender, fetch_versions=fetch, connection_manager=manager)
        await service.on_event(MinecraftEvent("server_started", "survival", {
            "minecraft_version": "1.21.8",
            "mods": [{"mod_id": "lithium", "version": "1.0.0"}],
        }))
        manager.connected = False
        await service.run_once()
        assert calls == []
        assert sender.messages == []
        manager.connected = True
        await service.run_once()
        assert len(sender.messages) == 1
    asyncio.run(scenario())
