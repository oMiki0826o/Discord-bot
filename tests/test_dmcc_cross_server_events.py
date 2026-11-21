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


def test_cross_server_defaults_enable_common_public_events():
    settings = DmccSettings.from_mapping(DEFAULT_SETTINGS, environ={})
    assert settings.cross_server_relay is True
    assert settings.cross_server_events == frozenset({
        "player_chat", "player_join", "player_quit", "player_death",
    })


def test_cross_server_relay_explicit_opt_out_is_preserved():
    settings = DmccSettings.from_mapping({
        **DEFAULT_SETTINGS,
        "cross_server_relay": False,
        "cross_server_events": ["player_chat"],
    }, environ={})
    assert settings.cross_server_relay is False
    assert settings.cross_server_events == frozenset({"player_chat"})


def test_cross_server_missing_options_use_safe_public_defaults():
    raw = {
        key: value for key, value in DEFAULT_SETTINGS.items()
        if key not in {"cross_server_relay", "cross_server_events"}
    }
    settings = DmccSettings.from_mapping(raw, environ={})
    assert settings.cross_server_relay is True
    assert settings.cross_server_events == frozenset({
        "player_chat", "player_join", "player_quit", "player_death",
    })


def test_default_join_and_quit_are_relayed_one_hop():
    class Gateway:
        def __init__(self):
            self.sent = []

        async def send_minecraft_message(self, server_id, message):
            self.sent.append((server_id, message))

    async def run():
        settings = DmccSettings.from_mapping(DEFAULT_SETTINGS, environ={})
        gateway = Gateway()
        relay = CrossServerRelayService(
            gateway,
            lambda: ("survival", "creative", "mirror"),
            event_types=settings.cross_server_events,
        )
        assert await relay.forward(MinecraftEvent(
            "player_join", "survival", {"player_name": "Steve"}
        ))
        assert await relay.forward(MinecraftEvent(
            "player_quit", "survival", {"player_name": "Steve"}
        ))
        assert gateway.sent == [
            ("creative", "[survival] Steve joined the game"),
            ("mirror", "[survival] Steve joined the game"),
            ("creative", "[survival] Steve left the game"),
            ("mirror", "[survival] Steve left the game"),
        ]
        assert not await relay.forward(MinecraftEvent(
            "link_request", "survival", {"code": "SECRET"}
        ))
        assert len(gateway.sent) == 4

    asyncio.run(run())

def test_cross_server_relay_continues_after_one_peer_disconnects():
    class Gateway:
        def __init__(self):
            self.sent = []

        async def send_minecraft_message(self, server_id, message):
            if server_id == "creative":
                raise ConnectionError("peer disconnected while forwarding")
            self.sent.append((server_id, message))

    async def run():
        gateway = Gateway()
        service = CrossServerRelayService(
            gateway, lambda: ("survival", "creative", "mirror"),
        )
        assert await service.forward(MinecraftEvent(
            "player_chat", "survival", {"player_name": "Steve", "message": "hello"},
        ))
        assert gateway.sent == [("mirror", "[survival] <Steve> hello")]

    asyncio.run(run())
