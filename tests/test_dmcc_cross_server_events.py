"""tests/test_dmcc_cross_server_events.py

Modification():

- Verify opt-in cross-server events preserve source and prevent private-data loops.
"""
from __future__ import annotations

import asyncio
import pytest
from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings, SettingsError
from bot.mod.dmcc.services.cross_server_relay import CrossServerRelayService


def test_cross_server_join_and_death_only_when_explicitly_enabled():
    class Gateway:
        def __init__(self):
            self.sent = []
        async def send_minecraft_message(self, server_id, message):
            self.sent.append((server_id, message))

    async def run():
        gateway = Gateway()
        service = CrossServerRelayService(
            gateway,
            lambda: ("survival", "creative"),
            event_types={"player_chat", "player_join", "player_death"},
        )
        assert await service.forward(MinecraftEvent(
            "player_join", "survival", {"player_name": "Steve"}
        ))
        assert gateway.sent == [("creative", "[survival] Steve joined the game")]
        assert await service.forward(MinecraftEvent(
            "player_death", "survival", {"death_message": "Steve fell"}
        ))
        assert gateway.sent[-1] == ("creative", "[survival] Steve fell")
        assert not await service.forward(MinecraftEvent(
            "server_metrics", "survival", {"mspt": 80}
        ))
        assert not await service.forward(MinecraftEvent(
            "link_request", "survival", {"code": "SECRET"}
        ))

    asyncio.run(run())


def test_cross_server_event_settings_reject_private_command_types():
    with pytest.raises(SettingsError):
        DmccSettings.from_mapping({
            **DEFAULT_SETTINGS,
            "cross_server_events": ["player_chat", "link_request"],
        }, environ={})


def test_cross_server_legacy_default_remains_chat_only():
    settings = DmccSettings.from_mapping(DEFAULT_SETTINGS, environ={})
    assert settings.cross_server_events == frozenset({"player_chat"})
