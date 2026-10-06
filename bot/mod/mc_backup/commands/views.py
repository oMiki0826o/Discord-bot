"""bot/mod/mc_backup/commands/views.py

Initiator-bound confirmations for destructive owner operations.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

Action = Callable[[], Awaitable[str]]


class OwnerConfirmationView(discord.ui.View):
    def __init__(self, *, initiator_id: int, timeout_seconds: float) -> None:
        super().__init__(timeout=timeout_seconds)
        self.initiator_id = initiator_id
        self._action: Action | None = None
        self._finished = False

    def allows(self, user_id: int) -> bool:
        return user_id == self.initiator_id

    def bind(self, action: Action) -> None:
        self._action = action

    def stop_for_test(self) -> None:
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.allows(interaction.user.id):
            return True
        await interaction.response.send_message("這個確認只屬於原始操作 Owner。", ephemeral=True)
        return False

    @discord.ui.button(label="確認", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self._action is None or self._finished:
            return
        self._finished = True
        try:
            result = await self._action()
        except Exception as exc:
            await interaction.response.send_message(f"操作失敗：{exc}", ephemeral=True)
        else:
            await interaction.response.send_message(result, ephemeral=True)
        self.stop()

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self._finished = True
        self.stop()
        await interaction.response.send_message("已取消。", ephemeral=True)
