"""bot/mod/dmcc/commands/owner.py
Owner-only prefix adapter for DMCC recovery and operations.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Any

from discord.ext import commands

from ..application.bridge_requests import BridgeRequestService
from ..application.channel_mappings import ChannelMappingService
from ..application.power import PowerService
from ..application.status import StatusQueryService
from ..domain.models import PowerAction
from ..services.info import InfoService


class DmccOwnerCog(commands.Cog):
    def __init__(
        self,
        bot: Any,
        *,
        info: InfoService,
        mappings: ChannelMappingService,
        bridge: BridgeRequestService,
        status: StatusQueryService,
        power: PowerService,
    ) -> None:
        self.bot = bot
        self._info = info
        self._mappings = mappings
        self._bridge = bridge
        self._status = status
        self._power = power

    @commands.group(name="dmcc", invoke_without_command=True)
    @commands.is_owner()
    async def dmcc_group(self, ctx: commands.Context) -> None:
        await ctx.send(
            "DMCC: status | map <server_id> <channel_id> | unmap <server_id> | "
            "console <server_id> <command> | reload"
        )

    @dmcc_group.command(name="status")
    @commands.is_owner()
    async def status(self, ctx: commands.Context) -> None:
        report = self._info.report()
        online = ", ".join(report.online_server_ids) if report.online_server_ids else "none"
        await ctx.send(f"DMCC online: {online}")

    @dmcc_group.command(name="map")
    @commands.is_owner()
    async def map_channel(self, ctx: commands.Context, server_id: str, channel_id: str) -> None:
        try:
            self._mappings.map(server_id, channel_id)
        except ValueError as exc:
            await ctx.send(f"DMCC mapping failed: {exc}")
            return
        await ctx.send(f"DMCC mapped `{server_id}` → `{channel_id}`.")

    @dmcc_group.command(name="unmap")
    @commands.is_owner()
    async def unmap_channel(self, ctx: commands.Context, server_id: str) -> None:
        try:
            removed = self._mappings.unmap(server_id)
        except ValueError as exc:
            await ctx.send(f"DMCC unmap failed: {exc}")
            return
        await ctx.send(
            f"DMCC unmapped `{server_id}`."
            if removed
            else f"DMCC has no mapping for `{server_id}`."
        )

    @dmcc_group.command(name="console")
    @commands.is_owner()
    async def console(self, ctx: commands.Context, server_id: str, *, command: str) -> None:
        try:
            output = await self._bridge.execute(server_id, command, 4)
        except (ConnectionError, LookupError, TimeoutError, ValueError) as exc:
            await ctx.send(f"DMCC console failed: {exc}")
            return
        await ctx.send(output or "DMCC command completed.")

    @dmcc_group.command(name="server-status")
    @commands.is_owner()
    async def server_status(self, ctx: commands.Context, server_id: str) -> None:
        try:
            status = await self._status.get(server_id)
        except (ConnectionError, LookupError, TimeoutError, ValueError) as exc:
            await ctx.send(f"DMCC status failed: {exc}")
            return
        await ctx.send(f"DMCC `{server_id}` bridge={status.bridge_state.value} process={status.process_state.value}")

    @dmcc_group.command(name="power")
    @commands.is_owner()
    async def power(self, ctx: commands.Context, server_id: str, action: str) -> None:
        try:
            selected = PowerAction(action.lower())
            await self._power.execute(server_id, selected, actor_level=4)
        except (ConnectionError, LookupError, TimeoutError, ValueError) as exc:
            await ctx.send(f"DMCC power failed: {exc}")
            return
        await ctx.send(f"DMCC `{server_id}` {selected.value} requested.")

    @dmcc_group.command(name="reload")
    @commands.is_owner()
    async def reload_module(self, ctx: commands.Context) -> None:
        loader = getattr(self.bot, "module_loader", None)
        if loader is None:
            await ctx.send(
                "DMCC reload is unavailable because the host module loader is not initialized."
            )
            return
        reloaded = await loader.reload("dmcc")
        await ctx.send(
            "DMCC module reloaded."
            if reloaded
            else "DMCC module reload failed; inspect the Bot log."
        )
