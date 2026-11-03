"""
bot/mod/agent/extension.py

Modification():

- 宣告 AI 前置依賴並附掛進階 Agent Runtime。
- 卸載時恢復 AI 基礎 Runtime，不建立 Discord 指令或資料庫。
"""

from __future__ import annotations

import logging
import weakref

logger = logging.getLogger(__name__)

MODULE_VERSION = "0.1.0"
MODULE_DISPLAY_NAME = "Agent"
MODULE_DEPENDENCIES = ("ai",)

_loaded_runtimes = weakref.WeakKeyDictionary()


async def setup(bot) -> None:
    """註冊獨立 Agent settings 與 read-only runtime extension。"""

    from bot.core.settings.manager import settings
    from bot.core.settings.schema import SettingRule

    from ..ai.api import register_runtime_extension, unregister_runtime_extension
    from .assembly import build_runtime_factory
    from .skills import initialize_skill_home

    try:
        initialize_skill_home()
    except OSError:
        logger.warning("Could not initialize editable Skill directory", exc_info=True)
    from .config import DEFAULT_SETTINGS, SETTINGS_NAME, build_settings_schema, AgentSettings
    from .status_cog import AgentStatusCog

    raw = settings.register(
        SETTINGS_NAME,
        DEFAULT_SETTINGS,
        build_settings_schema(SettingRule),
    )
    runtime = register_runtime_extension(
        bot,
        owner="agent",
        factory=build_runtime_factory(AgentSettings.from_mapping(raw)),
        read_only=True,
    )
    try:
        await bot.add_cog(AgentStatusCog(bot, AgentSettings.from_mapping(raw)))
    except BaseException:
        # A failed Cog registration must not leave AI pointing to an orphan Agent.
        try:
            unregister_runtime_extension(bot, owner="agent")
        finally:
            await runtime.close()
        raise
    _loaded_runtimes[bot] = runtime


async def teardown(bot) -> None:
    """解除 Agent 並關閉 runtime；可重複呼叫。"""

    runtime = _loaded_runtimes.pop(bot, None)
    if runtime is None:
        return
    from ..ai.api import unregister_runtime_extension

    try:
        await bot.remove_cog("AgentStatusCog")
    finally:
        try:
            removed = unregister_runtime_extension(bot, owner="agent")
        except Exception:
            await runtime.close()
            raise
        await removed.close()
