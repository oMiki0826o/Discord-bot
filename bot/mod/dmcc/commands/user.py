"""bot/mod/dmcc/commands/user.py
User-facing slash commands and Discord message relay listeners.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Any

from discord import app_commands
from discord.ext import commands

from ..application.bridge_requests import BridgeRequestService
from ..services.autocomplete import AutocompleteService
from ..services.command_catalog import CommandCatalog
from ..services.discord_relay import DiscordRelayService
from ..services.info import InfoService
from ..services.linking import LinkingService
from ..services.logs import render_log_excerpt
from ..services.op_levels import OpLevelResolver
from ..services.stats import render_stats_response
from ..services.whitelist import whitelist_add_command


_REQUEST_ERRORS = (ConnectionError, LookupError, TimeoutError, ValueError)


class DmccUserCog(commands.Cog):
    def __init__(
        self,
        bot: Any,
        *,
        relay: DiscordRelayService,
        linking: LinkingService,
        info: InfoService,
        catalog: CommandCatalog,
        op_levels: OpLevelResolver,
        bridge: BridgeRequestService,
        autocomplete: AutocompleteService,
    ) -> None:
        self.bot = bot
        self._relay = relay
        self._linking = linking
        self._info = info
        self._catalog = catalog
        self._op_levels = op_levels
        self._bridge = bridge
        self._autocomplete = autocomplete

    dmcc_slash = app_commands.Group(name="dmcc", description="Minecraft bridge commands")

    @dmcc_slash.command(name="help", description="Show DMCC commands available to you")
    async def slash_help(self, interaction) -> None:
        names = self._info.help_for(self._op_level(interaction))
        await interaction.response.send_message(
            "DMCC commands: " + ", ".join(f"`{name}`" for name in names),
            ephemeral=True,
        )

    @dmcc_slash.command(name="info", description="Show DMCC bridge status")
    async def slash_info(self, interaction) -> None:
        report = self._info.report()
        online = ", ".join(report.online_server_ids) if report.online_server_ids else "none"
        await interaction.response.send_message(
            f"DMCC online servers: {online}\nChannel mappings: {report.channel_mappings}",
            ephemeral=True,
        )

    @dmcc_slash.command(name="server-info", description="Show live information from a connected Minecraft server")
    async def slash_server_info(self, interaction, server_id: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            response = await self._bridge.server_info(server_id)
        except _REQUEST_ERRORS as exc:
            await interaction.followup.send(f"DMCC server info failed: {exc}", ephemeral=True)
            return
        await interaction.followup.send(
            "\n".join(
                (
                    f"Server: `{server_id}`",
                    f"Players: {response.get('online_players', '?')}/{response.get('max_players', '?')}",
                    "Online: " + self._player_names(response.get("player_names")),
                    f"Minecraft: {response.get('minecraft_version', '?')}",
                    f"MOTD: {response.get('motd', '')}",
                )
            ),
            ephemeral=True,
        )

    @dmcc_slash.command(name="console", description="Run a command on a connected Minecraft server")
    async def slash_console(self, interaction, server_id: str, command: str) -> None:
        level = self._op_level(interaction, server_id)
        if self._catalog.validate("console", level, (command,)) is not None:
            await interaction.response.send_message(
                "DMCC console is not authorized for this account.", ephemeral=True
            )
            return
        await self._execute(interaction, server_id, command, level, "console")

    @dmcc_slash.command(name="execute", description="Execute a command on a named connected Minecraft server")
    async def slash_execute(self, interaction, server_id: str, command: str) -> None:
        level = self._op_level(interaction, server_id)
        if self._catalog.validate("execute", level, (server_id, command)) is not None:
            await interaction.response.send_message(
                "DMCC execute is not authorized for this account.", ephemeral=True
            )
            return
        await self._execute(interaction, server_id, command, level, "execute")

    @slash_execute.autocomplete("command")
    async def execute_command_autocomplete(self, interaction, current: str) -> list[app_commands.Choice[str]]:
        server_id = getattr(getattr(interaction, "namespace", None), "server_id", None)
        if not isinstance(server_id, str) or not server_id.strip() or not current.strip():
            return []
        try:
            suggestions = await self._autocomplete.suggest(
                server_id,
                current,
                op_level=self._op_level(interaction, server_id),
            )
        except _REQUEST_ERRORS:
            return []
        return [
            app_commands.Choice(name=value[:100], value=value[:100])
            for value in suggestions[:25]
            if value
        ]

    @dmcc_slash.command(name="suggest", description="Ask Minecraft Brigadier for command suggestions")
    async def slash_suggest(self, interaction, server_id: str, command_input: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            suggestions = await self._autocomplete.suggest(
                server_id,
                command_input,
                op_level=self._op_level(interaction, server_id),
            )
        except _REQUEST_ERRORS as exc:
            await interaction.followup.send(f"DMCC suggestions failed: {exc}", ephemeral=True)
            return
        output = "No suggestions."
        if suggestions:
            output = "Suggestions: " + ", ".join(f"`{item}`" for item in suggestions[:25])
        await interaction.followup.send(output, ephemeral=True)

    @dmcc_slash.command(name="whitelist", description="Add a Minecraft player to a connected server whitelist")
    async def slash_whitelist(self, interaction, server_id: str, player_name: str) -> None:
        level = self._op_level(interaction, server_id)
        if self._catalog.validate("whitelist", level, (player_name,)) is not None:
            await interaction.response.send_message(
                "DMCC whitelist is not authorized for this account.", ephemeral=True
            )
            return
        try:
            command = whitelist_add_command(player_name)
        except ValueError as exc:
            await interaction.response.send_message(f"DMCC whitelist failed: {exc}", ephemeral=True)
            return
        await self._execute(interaction, server_id, command, level, "whitelist")

    @dmcc_slash.command(name="log", description="Read a bounded excerpt of a connected server's latest log")
    async def slash_log(self, interaction, server_id: str) -> None:
        if self._catalog.validate("log", self._op_level(interaction, server_id), ("latest.log",)) is not None:
            await interaction.response.send_message(
                "DMCC log is not authorized for this account.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            response = await self._bridge.log(server_id)
        except _REQUEST_ERRORS as exc:
            await interaction.followup.send(f"DMCC log failed: {exc}", ephemeral=True)
            return
        content = response.get("content")
        if not isinstance(content, str):
            await interaction.followup.send(
                f"DMCC log failed: {response.get('error', 'unavailable')}", ephemeral=True
            )
            return
        await interaction.followup.send(render_log_excerpt(content), ephemeral=True)

    @dmcc_slash.command(name="stats", description="Show a Minecraft player-stat leaderboard")
    async def slash_stats(self, interaction, server_id: str, stat_type: str, stat: str) -> None:
        if self._catalog.validate("stats", self._op_level(interaction, server_id), (stat_type, stat)) is not None:
            await interaction.response.send_message(
                "DMCC stats is not authorized for this account.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            output = render_stats_response(await self._bridge.stats(server_id, stat_type, stat))
        except _REQUEST_ERRORS as exc:
            await interaction.followup.send(f"DMCC stats failed: {exc}", ephemeral=True)
            return
        await interaction.followup.send(output, ephemeral=True)

    @dmcc_slash.command(name="link", description="Link your Discord account using a Minecraft-generated code")
    async def slash_link(self, interaction, code: str) -> None:
        if self._catalog.validate("link", self._op_level(interaction), (code,)) is not None:
            await interaction.response.send_message(
                "DMCC link is not authorized for this account.", ephemeral=True
            )
            return
        try:
            account = self._linking.confirm_discord_link(code, str(interaction.user.id))
        except ValueError as exc:
            await interaction.response.send_message(f"DMCC link failed: {exc}", ephemeral=True)
            return
        if account is None:
            await interaction.response.send_message(
                "DMCC link code is invalid or expired.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Linked Minecraft account `{account.minecraft_name}`.", ephemeral=True
        )

    @dmcc_slash.command(name="unlink", description="Unlink all of your Minecraft accounts")
    async def slash_unlink(self, interaction) -> None:
        removed = self._linking.unlink_discord(str(interaction.user.id))
        message = "No linked Minecraft accounts found."
        if removed:
            message = f"Unlinked {removed} Minecraft account(s)."
        await interaction.response.send_message(message, ephemeral=True)

    @dmcc_slash.command(name="links", description="List linked Minecraft accounts for a Discord user")
    async def slash_links(self, interaction, discord_user_id: str) -> None:
        if self._catalog.validate("links", self._op_level(interaction), ()) is not None:
            await interaction.response.send_message(
                "DMCC links is not authorized for this account.", ephemeral=True
            )
            return
        accounts = self._linking.links_for_discord(discord_user_id)
        if not accounts:
            await interaction.response.send_message(
                "No linked Minecraft accounts found.", ephemeral=True
            )
            return
        lines = "\n".join(
            f"- `{account.minecraft_name}` (`{account.minecraft_uuid}`)"
            for account in accounts
        )
        await interaction.response.send_message(
            f"Linked accounts for `{discord_user_id}`:\n{lines}", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: Any) -> None:
        if bool(getattr(getattr(message, "author", None), "bot", False)):
            return
        channel_id = getattr(getattr(message, "channel", None), "id", None)
        author = getattr(message, "author", None)
        if channel_id is None or author is None:
            return
        await self._relay.forward_message(
            str(getattr(message, "id", "")),
            str(channel_id),
            str(getattr(author, "display_name", author)),
            str(getattr(message, "content", "")),
            reply_preview=self._reply_preview(message),
            attachment_urls=tuple(
                str(getattr(item, "url", ""))
                for item in tuple(getattr(message, "attachments", ()) or ())
            ),
        )

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: Any) -> None:
        data = getattr(payload, "data", {})
        content = data.get("content") if isinstance(data, dict) else None
        if isinstance(content, str):
            await self._relay.forward_edit(str(getattr(payload, "message_id", "")), content)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: Any) -> None:
        await self._relay.forward_delete(str(getattr(payload, "message_id", "")))

    async def send_discord_message(self, channel_id: str, content: str) -> None:
        try:
            channel = self.bot.get_channel(int(channel_id))
        except ValueError:
            return
        if channel is not None and hasattr(channel, "send"):
            await channel.send(content)

    async def _execute(
        self,
        interaction: Any,
        server_id: str,
        command: str,
        level: int,
        operation: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            output = await self._bridge.execute(server_id, command, level)
        except _REQUEST_ERRORS as exc:
            await interaction.followup.send(f"DMCC {operation} failed: {exc}", ephemeral=True)
            return
        fallback = "Minecraft whitelist updated." if operation == "whitelist" else "DMCC command completed."
        await interaction.followup.send(output or fallback, ephemeral=True)

    def _op_level(self, interaction: Any, server_id: str | None = None) -> int:
        user = interaction.user
        roles = tuple(getattr(user, "roles", ()))
        return self._op_levels.resolve(
            str(user.id),
            (str(role.id) for role in roles),
            server_id,
            discord_user_name=getattr(user, "name", None),
            role_names=(str(getattr(role, "name", "")) for role in roles),
        )

    @staticmethod
    def _reply_preview(message: Any) -> str | None:
        reference = getattr(message, "reference", None)
        resolved = None if reference is None else getattr(reference, "resolved", None)
        if resolved is None:
            return None
        author = getattr(resolved, "author", None)
        content = str(getattr(resolved, "content", "")).strip()
        if author is None or not content:
            return None
        return f"{getattr(author, 'display_name', author)}: {content}"

    @staticmethod
    def _player_names(raw: object) -> str:
        if not isinstance(raw, list):
            return "none"
        names = [name for name in raw if isinstance(name, str) and name]
        return ", ".join(names) if names else "none"
