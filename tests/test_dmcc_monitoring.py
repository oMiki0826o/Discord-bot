"""tests/test_dmcc_monitoring.py

Modification():

- Test bounded and permission-aware Minecraft telemetry, alerts, channel monitors and presence.

"""
from __future__ import annotations

import asyncio
import pytest

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.monitoring import MonitoringConfig, MonitoringService


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.topic = None
        self.name = ""

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeBot:
    def __init__(self):
        self.channels = {str(i): FakeChannel() for i in (111111111111111111, 222222222222222222, 333333333333333333)}
        self.presence = None
        self.refresh_calls = 0
        self.clear_calls = []

    def get_channel(self, channel_id):
        return self.channels.get(str(channel_id))

    def set_presence_override(self, owner, text, status):
        self.presence = (owner, text, status)
        return True

    async def refresh_presence(self):
        self.refresh_calls += 1

    async def clear_presence_override(self, owner):
        self.clear_calls.append(owner)


class FakeManager:
    def __init__(self):
        self.connected = {"survival"}

    def get(self, name):
        return object() if name in self.connected else None


def _config(**options):
    return MonitoringConfig.from_mapping({
        "enabled": True,
        "presence": True,
        "interval_seconds": 60,
        "servers": {"survival": {
            "label": "生存服",
            "alert_channel_id": "111111111111111111",
            "topic_channel_id": "222222222222222222",
            "status_voice_channel_id": "333333333333333333",
            "mspt_threshold": 45,
            "mspt_recovery": 40,
            **options,
        }},
    }, {"survival"})


def test_bad_settings_fail_closed():
    for raw in [
        {"enabled": "true"},
        {"servers": {"unknown": {}}},
        {"servers": {"survival": {"mspt_threshold": -1}}},
        {"servers": {"survival": {"mspt_threshold": 40, "mspt_recovery": 42}}},
        {"servers": {"survival": {"topic_channel_id": "bad"}}},
        {"interval_seconds": 1},
    ]:
        with pytest.raises(ValueError):
            MonitoringConfig.from_mapping(raw, {"survival"})


def test_monitor_alert_recovery_presence_and_changed_only_edits():
    async def check():
        clock = [1000.0]
        bot, manager = FakeBot(), FakeManager()
        monitor = MonitoringService(bot, manager, _config(), clock=lambda: clock[0])
        def event(mspt):
            return MinecraftEvent("server_metrics", "survival", {
                "mspt": mspt, "tps": 1000 / mspt, "online_players": 3, "max_players": 20,
            })
        await monitor.on_event(event(49.0))
        await monitor.run_once()
        assert bot.channels["111111111111111111"].sent == []
        assert bot.presence == ("dmcc", "Minecraft | 3 人在線", "online")
        assert bot.channels["222222222222222222"].edits[-1]["topic"] == "生存服 | Online | 3/20 | 49.0 MSPT"
        assert bot.channels["333333333333333333"].edits[-1]["name"] == "生存服 · Online"
        clock[0] += 60
        await monitor.on_event(event(50.0))
        await monitor.run_once()
        assert len(bot.channels["111111111111111111"].sent) == 1
        assert "MSPT" in bot.channels["111111111111111111"].sent[0][0]
        await monitor.run_once()
        assert len(bot.channels["111111111111111111"].sent) == 1
        assert len(bot.channels["222222222222222222"].edits) == 1  # Discord channel edits have a cooldown.
        clock[0] += 601
        await monitor.on_event(event(38.0))
        await monitor.run_once()
        assert len(bot.channels["111111111111111111"].sent) == 2
        assert "恢復" in bot.channels["111111111111111111"].sent[1][0]
        manager.connected.clear()
        clock[0] += 601
        await monitor.run_once()
        assert bot.presence == ("dmcc", "Minecraft | 0 人在線", "dnd")
        assert bot.channels["333333333333333333"].edits[-1]["name"] == "生存服 · Offline"
        await monitor.close()
        assert bot.clear_calls == ["dmcc"]

    asyncio.run(check())


def test_invalid_or_stale_metrics_cannot_raise_alert():
    async def check():
        clock = [1000.0]
        bot, manager = FakeBot(), FakeManager()
        monitor = MonitoringService(bot, manager, _config(), clock=lambda: clock[0])
        for data in [
            {"mspt": True, "online_players": 3, "max_players": 20},
            {"mspt": float("nan"), "online_players": 3, "max_players": 20},
            {"mspt": -10, "online_players": 3, "max_players": 20},
        ]:
            await monitor.on_event(MinecraftEvent("server_metrics", "survival", data))
        assert monitor.latest("survival") is None
        await monitor.on_event(MinecraftEvent("server_metrics", "survival", {
            "mspt": 100.0, "online_players": 1, "max_players": 20,
        }))
        clock[0] += 400
        await monitor.run_once()
        assert not bot.channels["111111111111111111"].sent
        await monitor.close()

    asyncio.run(check())


def test_disabled_monitor_has_no_side_effects():
    async def check():
        bot = FakeBot()
        monitor = MonitoringService(
            bot, FakeManager(), MonitoringConfig.from_mapping({}, {"survival"})
        )
        await monitor.on_event(MinecraftEvent("server_metrics", "survival", {
            "mspt": 100, "online_players": 1, "max_players": 20,
        }))
        await monitor.run_once()
        assert bot.presence is None
        assert not any(channel.sent or channel.edits for channel in bot.channels.values())
        await monitor.close()

    asyncio.run(check())
