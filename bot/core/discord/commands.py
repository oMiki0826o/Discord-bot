"""
bot/core/discord/commands.py

Modification():

- 統一管理 Prefix 指令前綴。
- 統一管理 Slash Command 全域錯誤處理。
- 統一管理 Prefix Command 全域錯誤處理。
- 將未處理指令錯誤交由 Python Logging Infrastructure 處理。

本檔負責 Discord Bot 的全域 Command 基礎功能。
各功能模組的實際指令與業務邏輯不應放置於此。
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.logging.manager import LogManager
from bot.core.settings.manager import get


logger = LogManager().get_logger("bot.commands")


# ── Prefix 指令前綴 ──────────────────────

def dynamic_command_prefix(
    bot: commands.Bot,
    message: discord.Message,
) -> list[str]:
    """
    動態取得目前 Bot 的 Prefix 指令前綴。

    每次解析 Prefix Command 時重新讀取 Settings，
    因此 Settings 更新後不需要重新建立 Bot。
    """

    # 預設使用 $；若 Settings 中已有設定，則使用設定值。
    prefix = str(get("bot.command_prefix", "$")).strip() or "$"

    return commands.when_mentioned_or(prefix)(bot, message)


# ── Interaction 錯誤回覆 ──────────────────────

async def send_interaction_error(
    interaction: discord.Interaction,
    message: str,
) -> None:
    """
    向 Discord Interaction 傳送錯誤訊息。

    若 Interaction 已經回覆，則改用 Followup，
    避免重複回覆 Interaction。
    """

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )

    except discord.HTTPException as exc:
        # Interaction token 已過期（10062），或 Discord 已確認該 Interaction
        # （40060）時，不可能再傳送任何回覆；避免把同一件事記成第二個錯誤。
        if exc.code in {10062, 40060}:
            logger.info(
                "Interaction 已過期或已確認，略過錯誤回覆 user=%s guild=%s code=%s",
                interaction.user.id,
                interaction.guild_id,
                exc.code,
            )
            return

        logger.exception(
            "Interaction 錯誤訊息傳送失敗 user=%s guild=%s",
            interaction.user.id,
            interaction.guild_id,
        )

    except Exception:
        logger.exception(
            "Interaction 錯誤訊息傳送失敗 user=%s guild=%s",
            interaction.user.id,
            interaction.guild_id,
        )


# ── Slash Command Tree ──────────────────────

class CustomCommandTree(app_commands.CommandTree):
    """提供全域 Slash Command 錯誤處理的 CommandTree。"""

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """處理未被個別 Slash Command 捕捉的錯誤。"""

        if isinstance(error, app_commands.CommandNotFound):
            await send_interaction_error(
                interaction,
                "找不到這個指令，可能尚未同步或已被移除。",
            )
            return

        if isinstance(error, app_commands.MissingPermissions):
            await send_interaction_error(
                interaction,
                "你沒有執行這個指令所需的權限。",
            )
            return

        if isinstance(error, app_commands.BotMissingPermissions):
            await send_interaction_error(
                interaction,
                "Bot 缺少執行這個指令所需的 Discord 權限。",
            )
            return

        if isinstance(error, app_commands.CommandOnCooldown):
            await send_interaction_error(
                interaction,
                f"指令冷卻中，請於 {error.retry_after:.1f} 秒後再試。",
            )
            return

        if isinstance(error, app_commands.CheckFailure):
            await send_interaction_error(
                interaction,
                "目前無法執行這個指令。",
            )
            return

        original_error = (
            error.original
            if isinstance(error, app_commands.CommandInvokeError)
            else error
        )

        logger.error(
            "Slash Command 執行失敗 command=%s user=%s guild=%s",
            getattr(interaction.command, "qualified_name", None),
            interaction.user.id,
            interaction.guild_id,
            exc_info=(
                type(original_error),
                original_error,
                original_error.__traceback__,
            ),
        )

        await send_interaction_error(
            interaction,
            "指令執行時發生錯誤。",
        )



# ── Prefix Command 錯誤處理 ──────────────────────

async def handle_command_error(
    ctx: commands.Context,
    error: commands.CommandError,
) -> None:
    """處理未被個別 Prefix Command 捕捉的錯誤。"""

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"缺少必要參數：`{error.param.name}`"
        )
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(
            "指令參數格式錯誤。"
        )
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            "你沒有執行這個指令所需的權限。"
        )
        return

    if isinstance(error, commands.BotMissingPermissions):
        await ctx.send(
            "Bot 缺少執行這個指令所需的 Discord 權限。"
        )
        return

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"指令冷卻中，請於 {error.retry_after:.1f} 秒後再試。"
        )
        return

    if isinstance(error, commands.CheckFailure):
        await ctx.send(
            "目前無法執行這個指令。"
        )
        return

    original_error = (
        error.original
        if isinstance(error, commands.CommandInvokeError)
        else error
    )

    logger.error(
        "Prefix Command 執行失敗 command=%s user=%s guild=%s",
        getattr(ctx.command, "qualified_name", None),
        ctx.author.id,
        ctx.guild.id if ctx.guild else None,
        exc_info=(
            type(original_error),
            original_error,
            original_error.__traceback__,
        ),
    )

    await ctx.send(
        "指令執行時發生錯誤。"
    )
