"""
bot/mod/agent/status_cog.py

Modification():
- Provide a read-only status command for configured Discord IDs and bot owner.
- Never disclose prompts, other users' memories, or API secrets.
"""
from __future__ import annotations

from discord.ext import commands

from ..ai.api import get_runtime_host
from .config import AgentSettings


class AgentStatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings: AgentSettings) -> None:
        self.bot = bot
        self.settings = settings

    @commands.command(name="agentstatus")
    async def agent_status(self, ctx: commands.Context) -> None:
        allowed = await self.bot.is_owner(ctx.author)
        if not allowed:
            allowed = self.settings.is_privileged(ctx.author.id)
        if not allowed:
            await ctx.send("無權限檢視 Agent 狀態。")
            return
        try:
            runtime = get_runtime_host(self.bot).active
            runtime_name = type(runtime).__name__
        except RuntimeError:
            runtime_name = "Unavailable"
        await ctx.send(
            f"Agent Runtime: {runtime_name}\n"
            f"Max model turns: {self.settings.max_model_turns}\n"
            f"Max tool calls: {self.settings.max_tool_calls}\n"
            "Tools: read-only"
        )
