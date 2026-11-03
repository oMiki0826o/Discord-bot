"""
tests/test_agent_extension_lifecycle.py

Modification():
- Ensure Cog registration failure rolls back Agent runtime without leaking state.
- Keep AI active Runtime safe during partial Agent module load.
"""
from __future__ import annotations

import asyncio

import pytest

from bot.mod.agent import extension
from bot.mod.agent.config import DEFAULT_SETTINGS


def test_agent_setup_rolls_back_runtime_when_discord_cog_add_fails(monkeypatch, tmp_path) -> None:
    import bot.core.settings.manager as settings_manager
    import bot.mod.ai.api as ai_api
    from bot.mod.agent.skills import bootstrap

    class FakeBot:
        async def add_cog(self, cog):
            raise RuntimeError("Discord Cog registration failed")

    class Runtime:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    bot = FakeBot()
    runtime = Runtime()
    removed = []
    monkeypatch.setattr(settings_manager.settings, "register", lambda *args, **kwargs: DEFAULT_SETTINGS)
    monkeypatch.setattr(bootstrap, "initialize_skill_home", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(extension, "initialize_skill_home", lambda *args, **kwargs: tmp_path, raising=False)
    monkeypatch.setattr(ai_api, "register_runtime_extension", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(ai_api, "unregister_runtime_extension", lambda bot, *, owner: removed.append(owner) or runtime)

    async def run():
        with pytest.raises(RuntimeError, match="registration failed"):
            await extension.setup(bot)

    asyncio.run(run())
    assert removed == ["agent"]
    assert runtime.closed
    assert bot not in extension._loaded_runtimes
