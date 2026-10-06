"""bot/mod/dmcc/commands/views.py
User-bound confirmation components for destructive owner operations.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Any

from discord import ButtonStyle, ui


class OwnerConfirmationView(ui.View):
    def __init__(self, *, owner_id: int, timeout: float = 30.0) -> None:
        super().__init__(timeout=timeout)
        self._owner_id = owner_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: Any) -> bool:
        return int(getattr(interaction.user, "id", -1)) == self._owner_id

    @ui.button(label="Confirm", style=ButtonStyle.danger)
    async def confirm(self, interaction: Any, button: ui.Button) -> None:
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @ui.button(label="Cancel", style=ButtonStyle.secondary)
    async def cancel(self, interaction: Any, button: ui.Button) -> None:
        self.confirmed = False
        await interaction.response.defer()
        self.stop()
