"""tests/test_dmcc_presence.py

Modification():

- Ensure DMCC Presence overrides are opt-in and independently reversible.

"""
from __future__ import annotations

import asyncio

from bot.core.discord.client import DiscordBot


def test_presence_owner_conflicts_and_release(monkeypatch) -> None:
    async def scenario() -> None:
        bot = DiscordBot()
        try:
            captured = []
            async def change_presence(*, activity, status):
                captured.append((activity, status))
            monkeypatch.setattr(bot, "change_presence", change_presence)
            assert bot.set_presence_override("dmcc", "Minecraft | 5 人在線", "online") is True
            assert bot.set_presence_override("other", "overwrite", "idle") is False
            activity, status = await bot.refresh_presence()
            assert activity.name == "Minecraft | 5 人在線"
            await bot.clear_presence_override("other")
            activity, status = await bot.refresh_presence()
            assert activity.name == "Minecraft | 5 人在線"
            await bot.clear_presence_override("dmcc")
            activity, status = await bot.refresh_presence()
            assert activity is None or activity.name != "Minecraft | 5 人在線"
            assert len(captured) >= 3
        finally:
            await bot.close()
    asyncio.run(scenario())
