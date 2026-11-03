"""
bot/core/discord/client.py

Modification():

- 建立 Discord Bot 核心 Client。
- 管理 Discord Client 基礎生命週期。
- 管理 Bot Ready 狀態。
- 提供 Application 關閉請求訊號。
- 管理 Module 初始化。
- 管理 Prefix Command 全域錯誤委派。
- 管理 Slash Command 同步。
- 管理 Discord Presence 更新。
- 顯示 Bot 首次啟動資訊。

本檔只負責 Discord Client 與 Discord 初始化生命週期，
不負責 Application 啟動或功能模組業務邏輯。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bot.core.discord.commands import (
    CustomCommandTree,
    dynamic_command_prefix,
    handle_command_error,
)
from bot.core.discord.presence import build_presence
from bot.core.discord.intents import build_intents
from bot.core.discord.natural_command import dispatch_message
from bot.core.discord.owner import is_owner
from bot.core.settings.manager import get

if TYPE_CHECKING:
    from bot.core.modules.loader import ModuleLoader


# ── Discord Bot ──────────────────────

class DiscordBot(commands.Bot):
    """Discord Bot 核心 Client。"""

    def __init__(self) -> None:
        super().__init__(
            command_prefix=dynamic_command_prefix,
            intents=build_intents(),
            tree_cls=CustomCommandTree,
            help_command=None,
        )

        self.ready_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()

        self.startup_time = time.perf_counter()

        self._ready_once = False
        self._module_loader: ModuleLoader | None = None
        self._presence_override: tuple[str, str, str] | None = None

    async def is_owner(self, user: discord.abc.User) -> bool:
        """套用全專案共用的 Owner Policy。"""

        return await is_owner(self, user)

    # ── Module Loader ──────────────────────

    def set_module_loader(
        self,
        loader: ModuleLoader,
    ) -> None:
        """設定 Discord 初始化階段使用的 Module Loader。"""

        if self._module_loader is not None:
            raise RuntimeError(
                "Module Loader 已經設定"
            )

        self._module_loader = loader

    @property
    def module_loader(
        self,
    ) -> ModuleLoader | None:
        """取得目前使用的 Module Loader。"""

        return self._module_loader

    # ── Discord 初始化 ──────────────────────

    async def setup_hook(self) -> None:
        """執行 Discord Client非同步初始化。"""

        if self._module_loader is not None:
            await self._module_loader.load_all()

        await self.sync_slash()

    # ── Ready ──────────────────────

    async def on_ready(self) -> None:
        """處理 Discord Client Ready 事件。"""

        if self.user is None:
            return

        activity, _ = await self.refresh_presence()

        if self._ready_once:
            return

        self._ready_once = True
        self.ready_event.set()

        startup_elapsed = (
            time.perf_counter()
            - self.startup_time
        )

        prefix = self.get_prefix_for_display()

        if activity is None:
            presence_text = "無"
        else:
            presence_text = (
                f"{activity.type.name} "
                f"{activity.name}"
            )

        user_count = sum(
            guild.member_count or 0
            for guild in self.guilds
        )

        separator = "-" * 60

        print(separator)
        print("Discord Bot 啟動完成")
        print(separator)
        print(f"登入身份：{self.user}")
        print(f"Discord ID：{self.user.id}")
        print(f"指令前綴：{prefix}")
        print(f"伺服器數量：{len(self.guilds)}")
        print(f"使用者數量：{user_count}")
        print(f"目前狀態：{presence_text}")
        print(f"啟動耗時：{startup_elapsed:.2f} 秒")
        print(separator)

    # ── Application Lifecycle ──────────────────────

    def request_shutdown(self) -> None:
        """向 Application 請求安全關閉 Bot。"""

        self.shutdown_event.set()

    # ── Prefix Command ──────────────────────

    def get_prefix_for_display(self) -> str:
        """取得目前設定的 Prefix，供狀態顯示使用。"""

        return str(
            get(
                "bot.command_prefix",
                "$",
            )
        ).strip() or "$"

    async def on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        """將 Prefix Command 錯誤交由 Command 系統處理。"""

        await handle_command_error(
            ctx,
            error,
        )

    # ── Message Dispatch ──────────────────────

    async def on_message(
        self,
        message: discord.Message,
    ) -> None:
        """先分派自然語言指令，再交由 Prefix Command 處理。"""

        if await dispatch_message(
            message,
            bot_user_id=self.user.id if self.user is not None else None,
        ):
            return

        await self.process_commands(message)

    # ── Slash Command ──────────────────────

    async def sync_slash(self) -> None:
        """同步全域 Slash Commands。"""

        await self.tree.sync()

    # ── Presence ──────────────────────

    def set_presence_override(self, owner: str, activity_text: str, status: str) -> bool:
        """Set an explicitly configured module-owned override without stealing another's."""
        if not owner or not activity_text or status not in {"online", "idle", "dnd", "invisible"}:
            raise ValueError("Invalid Presence override")
        existing = self._presence_override
        if existing is not None and existing[0] != owner:
            return False
        self._presence_override = (owner, activity_text[:128], status)
        return True

    async def clear_presence_override(self, owner: str) -> None:
        """Restore the user's normal Presence only if this module owns the override."""
        existing = self._presence_override
        if existing is not None and existing[0] == owner:
            self._presence_override = None
            await self.refresh_presence()

    async def refresh_presence(
        self,
    ) -> tuple[
        discord.Activity | None,
        discord.Status,
    ]:
        """重新讀取 Settings 並更新 Discord Presence。"""

        activity, status = build_presence()
        override = self._presence_override
        if override is not None:
            _, text, overridden_status = override
            activity = discord.Game(name=text)
            status = getattr(discord.Status, overridden_status)

        await self.change_presence(
            activity=activity,
            status=status,
        )

        return activity, status
