"""tests/test_dmcc_module.py

Modification():

- Verifies the formal DMCC module lifecycle without a Discord connection.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


class _Settings:
    def register(self, _name, defaults, *_schema):
        return {**defaults, "gateway": {"host": "127.0.0.1", "port": 0}}


class _Bot:
    def __init__(self) -> None:
        self.cogs: dict[str, object] = {}

    async def add_cog(self, cog) -> None:
        self.cogs[cog.qualified_name] = cog

    def get_cog(self, name: str):
        return self.cogs.get(name)

    async def remove_cog(self, name: str) -> None:
        self.cogs.pop(name, None)

    def get_channel(self, _channel_id: int):
        return None


def test_formal_dmcc_module_loads_and_tears_down(tmp_path: Path) -> None:
    from bot.mod.dmcc.extension import setup, teardown

    async def scenario() -> None:
        bot = _Bot()
        await setup(bot, settings_registry=_Settings(), state_path=tmp_path / "state.json")
        assert set(bot.cogs) == {"DmccUserCog", "DmccOwnerCog"}
        await teardown(bot)
        assert bot.cogs == {}

    asyncio.run(scenario())
