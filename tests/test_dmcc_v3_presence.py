"""tests/test_dmcc_v3_presence.py

Modification():

- Verify DMCC v3 three-state status and dedicated voice player counter.
"""
from __future__ import annotations

import asyncio
from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.monitoring import MonitoringConfig, MonitoringService


def test_presence_online_idle_dnd_and_player_count_voice() -> None:
    class Channel:
        def __init__(self):
            self.edits = []
        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    class Bot:
        def __init__(self):
            self.presence = None
            self.channels = {123456789012345678: Channel()}
        def get_channel(self, value):
            return self.channels.get(value)
        def set_presence_override(self, owner, text, status):
            self.presence = (owner, text, status)
            return True
        async def refresh_presence(self):
            return None
        async def clear_presence_override(self, owner):
            return None

    class Manager:
        connected = True
        def get(self, name):
            return object() if self.connected else None

    async def check():
        clock = [1000.]
        bot, manager = Bot(), Manager()
        cfg = MonitoringConfig.from_mapping({
            "enabled": True, "presence": True,
            "servers": {"survival": {
                "label": "生存服",
                "player_count_voice_channel_id": "123456789012345678",
            }},
        }, {"survival"})
        monitor = MonitoringService(bot, manager, cfg, clock=lambda: clock[0])
        await monitor.on_event(MinecraftEvent("server_metrics", "survival", {
            "mspt": 20.0, "online_players": 0, "max_players": 20,
        }))
        await monitor.run_once()
        assert bot.presence == ("dmcc", "Minecraft | 0 人在線", "idle")
        assert bot.channels[123456789012345678].edits[-1]["name"] == "生存服 · Players: 0/20"
        clock[0] += 601
        await monitor.on_event(MinecraftEvent("server_metrics", "survival", {
            "mspt": 20.0, "online_players": 3, "max_players": 20,
        }))
        await monitor.run_once()
        assert bot.presence == ("dmcc", "Minecraft | 3 人在線", "online")
        assert bot.channels[123456789012345678].edits[-1]["name"] == "生存服 · Players: 3/20"
        manager.connected = False
        clock[0] += 601
        await monitor.run_once()
        assert bot.presence == ("dmcc", "Minecraft | 0 人在線", "dnd")
        await monitor.close()

    asyncio.run(check())


def test_bad_voice_ids_are_rejected() -> None:
    try:
        MonitoringConfig.from_mapping({
            "enabled": True,
            "servers": {"survival": {"player_count_voice_channel_id": "abc"}},
        }, {"survival"})
    except ValueError:
        return
    raise AssertionError("invalid Discord channel ID should be rejected")
