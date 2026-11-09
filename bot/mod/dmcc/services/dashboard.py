"""bot/mod/dmcc/services/dashboard.py

Modification():

- Offer native, user-scoped Discord buttons and server-select interactions.
- Recheck requester identity on every click; never execute arbitrary commands
  or forward third-party component custom IDs.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
import logging
import re

import discord

LOG = logging.getLogger(__name__)
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DmccDashboardView(discord.ui.View):
    """Bounded ephemeral navigation for the bridge's OWN interactive controls."""

    def __init__(
        self, requester_id: int, servers: Sequence[str],
        fetch_summary: Callable[[], str],
        fetch_server: Callable[[str], Awaitable[str]],
        *, selected: str | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self._requester_id = int(requester_id)
        self._fetch_summary = fetch_summary
        self._fetch_server = fetch_server
        self._selected = selected
        self._servers = tuple(
            value for value in dict.fromkeys(servers)
            if isinstance(value, str) and _ID.fullmatch(value)
        )[:25]
        refresh = discord.ui.Button(
            label="重新整理", emoji=None, style=discord.ButtonStyle.secondary
        )
        refresh.callback = self._refresh
        self.add_item(refresh)

        if self._servers:
            menu = discord.ui.Select(
                placeholder="選擇 Minecraft 伺服器",
                options=[
                    discord.SelectOption(label=server, value=server)
                    for server in self._servers
                ],
                min_values=1, max_values=1,
            )
            menu.callback = self._choose
            self.add_item(menu)
            self._selector = menu
        else:
            self._selector = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._requester_id:
            return True
        await interaction.response.send_message(
            "這份 DMCC 控制面板僅限原始使用者操作。", ephemeral=True,
        )
        return False

    async def _fetch(self, server_id: str | None) -> str:
        if server_id is None:
            return self._fetch_summary()[:1900]
        if server_id not in self._servers:
            return "該伺服器不在已授權的清單中。"
        try:
            text = await self._fetch_server(server_id)
            return text[:1900]
        except (ConnectionError, LookupError, TimeoutError, ValueError):
            return "伺服器目前未連線，或資訊取得失敗。"
        except Exception:
            LOG.exception("DMCC dashboard server status failed")
            return "伺服器狀態無法取得。"

    async def _refresh(self, interaction: discord.Interaction) -> None:
        text = await self._fetch(self._selected)
        await interaction.response.edit_message(content=text, view=self)

    async def _choose(self, interaction: discord.Interaction) -> None:
        if self._selector is None or not self._selector.values:
            await interaction.response.send_message("沒有可選擇的伺服器。", ephemeral=True)
            return
        selected = self._selector.values[0]
        if selected not in self._servers:
            await interaction.response.send_message("不支援的伺服器。", ephemeral=True)
            return
        self._selected = selected
        text = await self._fetch(selected)
        await interaction.response.edit_message(content=text, view=self)
