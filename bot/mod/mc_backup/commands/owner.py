"""bot/mod/mc_backup/commands/owner.py

Owner-only prefix commands for local backup maintenance.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Any

from discord.ext import commands

from ..application.backup import BackupCoordinator
from ..application.schedules import BackupScheduleService
from ..config import McBackupSettings
from ..domain.models import BackupSchedule
from .views import OwnerConfirmationView


class McBackupOwnerCog(commands.Cog):
    def __init__(self, bot: Any, *, settings: McBackupSettings, coordinator: BackupCoordinator, schedules: BackupScheduleService, confirmation_timeout_seconds: float) -> None:
        self.bot = bot
        self._settings = settings
        self._coordinator = coordinator
        self._schedules = schedules
        self._confirmation_timeout_seconds = confirmation_timeout_seconds

    @commands.group(name="mcbackup", invoke_without_command=True)
    @commands.is_owner()
    async def mcbackup_group(self, ctx: commands.Context) -> None:
        await ctx.send("mcbackup: status | list <server> | create <server> [name] | restore <server> <artifact> | delete <server> <artifact> | schedule <server> <on|off> [HH:MM] [timezone]")

    @mcbackup_group.command(name="status")
    @commands.is_owner()
    async def status(self, ctx: commands.Context) -> None:
        states: list[str] = []
        for server in self._settings.servers:
            try:
                state = "running" if await self._coordinator.is_running(server) else "stopped"
            except Exception:
                state = "unknown"
            states.append(f"{server.server_id}: {state}")
        await ctx.send("MC backup status: " + (", ".join(states) if states else "no configured servers"))

    @mcbackup_group.command(name="list")
    @commands.is_owner()
    async def list_artifacts(self, ctx: commands.Context, server_id: str) -> None:
        try:
            artifacts = await self._coordinator.list(self._settings.require_server(server_id))
            message = ", ".join(item.artifact_id for item in artifacts) or "none"
        except Exception as exc:
            message = f"Backup list failed: {exc}"
        await ctx.send(f"Backups for `{server_id}`: {message}")

    @mcbackup_group.command(name="create")
    @commands.is_owner()
    async def create(self, ctx: commands.Context, server_id: str, name: str | None = None) -> None:
        try:
            artifact = await self._coordinator.create(self._settings.require_server(server_id), name=name)
        except Exception as exc:
            await ctx.send(f"Backup create failed: {exc}")
            return
        await ctx.send(f"Backup created: `{artifact.artifact_id}`")

    @mcbackup_group.command(name="restore")
    @commands.is_owner()
    async def restore(self, ctx: commands.Context, server_id: str, artifact_id: str) -> None:
        await self._confirm(ctx, f"Restore `{server_id}` from `{artifact_id}`?", lambda: self._restore(server_id, artifact_id))

    @mcbackup_group.command(name="delete")
    @commands.is_owner()
    async def delete(self, ctx: commands.Context, server_id: str, artifact_id: str) -> None:
        await self._confirm(ctx, f"Delete backup `{artifact_id}` for `{server_id}`?", lambda: self._delete(server_id, artifact_id))

    @mcbackup_group.command(name="schedule")
    @commands.is_owner()
    async def schedule(self, ctx: commands.Context, server_id: str, enabled: str, time_of_day: str = "03:30", timezone: str = "UTC") -> None:
        if enabled.lower() not in {"on", "off"}:
            await ctx.send("Schedule mode must be `on` or `off`.")
            return
        try:
            self._settings.require_server(server_id)
            await self._schedules.set_enabled(BackupSchedule(server_id, enabled.lower() == "on", time_of_day, timezone))
        except Exception as exc:
            await ctx.send(f"Schedule update failed: {exc}")
            return
        await ctx.send(f"Backup schedule for `{server_id}` is {enabled.lower()}.")

    async def _confirm(self, ctx: commands.Context, message: str, action) -> None:
        view = OwnerConfirmationView(initiator_id=ctx.author.id, timeout_seconds=self._confirmation_timeout_seconds)
        view.bind(action)
        await ctx.send(message, view=view)

    async def _restore(self, server_id: str, artifact_id: str) -> str:
        await self._coordinator.restore(self._settings.require_server(server_id), artifact_id)
        return f"Restored `{server_id}` from `{artifact_id}`."

    async def _delete(self, server_id: str, artifact_id: str) -> str:
        await self._coordinator.delete(self._settings.require_server(server_id), artifact_id)
        return f"Deleted `{artifact_id}`."
