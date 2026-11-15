"""
bot/mod/basic/help/command.py

Modification():

- 提供 Help Slash Command。
- 掃描目前已註冊的 Slash Commands。
- 將 Slash Commands 依功能 Module 分類。
- 建立 Help 分頁資料。
- 啟動 Help Discord UI。

本檔負責 /help 指令與 Help 資料建立，
不負責 Discord UI 元件實作。
"""

from __future__ import annotations

from collections import defaultdict

import discord

from discord import app_commands
from discord.ext import commands

from bot.core.discord.help.builder import build_help_categories, module_display_name
from bot.core.discord.help.models import HelpEntry
from bot.core.discord.help.view import HelpView


# ── Help 設定 ──────────────────────

# ── Command Module ──────────────────────

def _get_command_module(
    command: app_commands.Command,
) -> str:
    """取得 Slash Command 所屬功能 Module。"""

    binding = command.binding

    if binding is None:
        return "other"

    module_path = getattr(
        binding.__class__,
        "__module__",
        "",
    )

    parts = module_path.split(".")

    try:
        mod_index = parts.index("mod")
        return parts[mod_index + 1]

    except (
        ValueError,
        IndexError,
    ):
        return "other"


# ── Command 掃描 ──────────────────────

def _collect_commands(
    bot: commands.Bot,
) -> dict[str, list[HelpEntry]]:
    """收集目前 Command Tree 中所有 Slash Commands。"""

    categories: dict[
        str,
        list[HelpEntry],
    ] = defaultdict(list)

    for command in bot.tree.get_commands():

        if isinstance(
            command,
            app_commands.Group,
        ):
            _collect_group_commands(
                command,
                categories,
            )
            continue

        if not isinstance(
            command,
            app_commands.Command,
        ):
            continue

        module_name = _get_command_module(
            command
        )

        categories[module_name].append(
            HelpEntry(
                name=command.qualified_name,
                description=(
                    command.description
                    or "沒有說明"
                ),
            )
        )

    return dict(categories)


def _collect_group_commands(
    group: app_commands.Group,
    categories: dict[
        str,
        list[HelpEntry],
    ],
) -> None:
    """遞迴收集 Slash Command Group 內的指令。"""

    for command in group.commands:

        if isinstance(
            command,
            app_commands.Group,
        ):
            _collect_group_commands(
                command,
                categories,
            )
            continue

        if not isinstance(
            command,
            app_commands.Command,
        ):
            continue

        module_name = _get_command_module(
            command
        )

        categories[module_name].append(
            HelpEntry(
                name=command.qualified_name,
                description=(
                    command.description
                    or "沒有說明"
                ),
            )
        )


# ── Help Cog ──────────────────────

class HelpCog(commands.Cog):
    """提供 Bot Slash Command Help 功能。"""

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        self.bot = bot


    # ── Help ──────────────────────

    @app_commands.command(
        name="help",
        description="查看 Bot 指令說明。",
    )
    async def help(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """顯示目前 Bot 可用的 Slash Commands。"""

        # 指令清單會隨載入模組數量增加；先確認 Interaction，避免 Discord
        # 在初始回覆期限內未收到回應而使後續 Help 回覆失效。
        await interaction.response.defer(
            thinking=True,
        )

        commands_by_module = _collect_commands(
            self.bot
        )

        categories = build_help_categories(commands_by_module, category_name_resolver=lambda name: module_display_name(self.bot, name))

        if not categories:
            await interaction.followup.send(
                "目前沒有可顯示的指令。",
                ephemeral=True,
            )
            return

        view = HelpView(
            categories,
            user_id=interaction.user.id,
        )

        await interaction.followup.send(
            embed=view.build_embed(),
            view=view,
        )

        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            return
