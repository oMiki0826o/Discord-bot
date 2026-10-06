"""tests/test_mc_backup_module.py

Modification():

- Verifies the formal Minecraft backup module lifecycle without a Discord connection.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


class _Settings:
    def register(self, _name, defaults, *_schema):
        return defaults


class _Bot:
    def __init__(self) -> None:
        self.cogs: dict[str, object] = {}

    async def add_cog(self, cog) -> None:
        self.cogs[cog.qualified_name] = cog

    def get_cog(self, name: str):
        return self.cogs.get(name)

    async def remove_cog(self, name: str) -> None:
        self.cogs.pop(name, None)


def test_formal_mc_backup_module_loads_and_tears_down(tmp_path: Path) -> None:
    from bot.mod.mc_backup.extension import setup, teardown

    async def scenario() -> None:
        bot = _Bot()
        await setup(bot, settings_registry=_Settings(), data_dir=tmp_path)
        assert set(bot.cogs) == {"McBackupOwnerCog"}
        await teardown(bot)
        assert bot.cogs == {}

    asyncio.run(scenario())
