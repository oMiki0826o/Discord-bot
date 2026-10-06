"""
tests/test_owner_prefix_help.py

Modification():

- Owner Prefix Help must reflect the currently registered command tree.
- 維護 test owner prefix help 的發布版行為與驗證契約。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.mod.system.prefix_help.help import OwnerHelpCog


def _command(name: str, module: str, *, hidden: bool = False) -> SimpleNamespace:
    async def callback() -> None:
        return None

    callback.__module__ = module
    return SimpleNamespace(qualified_name=name, hidden=hidden, callback=callback)


def test_owner_help_scans_visible_ai_prefix_commands() -> None:
    class Bot:
        def walk_commands(self):
            return (
                _command("help", "bot.mod.system.prefix_help.help"),
                _command("ai", "bot.mod.ai.commands.discord"),
                _command("ai persona set", "bot.mod.ai.commands.discord"),
                _command("hidden-command", "bot.mod.ai.commands.discord", hidden=True),
            )

    class Context:
        embed = None
        view = None
        author = SimpleNamespace(id=123)

        async def send(self, *, embed=None, view=None) -> None:
            self.embed = embed
            self.view = view

    context = Context()
    asyncio.run(OwnerHelpCog(Bot())._send_overview(context))

    assert context.embed is not None
    assert "`$ai`" in context.embed.description
    assert "`$ai persona set`" in context.embed.description
    assert "hidden-command" not in context.embed.description
