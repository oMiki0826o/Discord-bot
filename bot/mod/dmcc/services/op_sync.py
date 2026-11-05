"""bot/mod/dmcc/services/op_sync.py

Modification():

- Optional Discord-authorized Minecraft operator policy with conservative fail-closed resolution.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import logging

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OpSyncConfig:
    enabled: bool = False
    guild_id: str | None = None
    interval_seconds: int = 600
    max_entries: int = 100
    allow_removals: bool = False

    @classmethod
    def from_mapping(cls, raw: object) -> "OpSyncConfig":
        if not isinstance(raw, Mapping) or set(raw) - {
            "enabled", "guild_id", "interval_seconds", "max_entries", "allow_removals",
        }:
            raise ValueError("op_sync must contain documented options")
        enabled = raw.get("enabled", False)
        guild_id = raw.get("guild_id")
        interval = raw.get("interval_seconds", 600)
        max_entries = raw.get("max_entries", 100)
        removals = raw.get("allow_removals", False)
        if type(enabled) is not bool or type(removals) is not bool:
            raise ValueError("op_sync flags must be booleans")
        if enabled and guild_id is None:
            raise ValueError("op_sync requires an explicit Discord guild")
        if guild_id is not None and (
            not isinstance(guild_id, str) or not guild_id.isascii()
            or not guild_id.isdecimal() or not 15 <= len(guild_id) <= 20
        ):
            raise ValueError("op_sync.guild_id must be a Discord ID")
        if type(interval) is not int or not 60 <= interval <= 86400:
            raise ValueError("op_sync.interval_seconds must be 60..86400")
        if type(max_entries) is not int or not 1 <= max_entries <= 100:
            # The Java OpSyncPolicy parser rejects snapshots above 100 entries.
            raise ValueError("op_sync.max_entries must be 1..100")
        return cls(enabled, guild_id, interval, max_entries, removals)


class OpSyncService:
    """Build least-privilege snapshots from linked UUIDs and cached guild roles.

    Never copies arbitrary Discord command requests into an OP mutation.
    Unknown members, missing permissions, and oversized snapshots abort the
    cycle, rather than treating an unresolved account as a permission revoke.
    """

    def __init__(
        self, config: OpSyncConfig, bot: object, links: object,
        resolver: object, manager: object, gateway: object,
    ) -> None:
        self.config = config
        self._bot, self._links = bot, links
        self._resolver, self._manager, self._gateway = resolver, manager, gateway
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> bool:
        if not self.config.enabled or self.config.guild_id is None:
            return False
        get_guild = getattr(self._bot, "get_guild", None)
        guild = get_guild(int(self.config.guild_id)) if callable(get_guild) else None
        if guild is None or not hasattr(guild, "get_member"):
            return False
        links = tuple(self._links.all_links())
        if not links or len(links) > self.config.max_entries:
            return False
        # Require all links to resolve before writing anything; this is not
        # a complete-operator-list reset, and does not touch unrelated admins.
        entries_by_server: dict[str, list[dict[str, object]]] = {}
        active_servers = sorted({
            item.server_id
            for item in self._manager.all()
            if isinstance(item.server_id, str) and item.server_id
        })
        if not active_servers:
            return False
        for server_id in active_servers:
            entries: list[dict[str, object]] = []
            for link in links:
                try:
                    member = guild.get_member(int(link.discord_user_id))
                except (ValueError, TypeError, AttributeError):
                    return False
                if member is None:
                    if self.config.allow_removals:
                        # A partial role snapshot must never revoke operator rights.
                        return False
                    continue
                roles = tuple(getattr(member, "roles", ()) or ())
                role_ids = tuple(str(role.id) for role in roles)
                # Native Minecraft OP is privileged and persistent. Do not
                # authorize it through mutable Discord usernames or role names.
                # Command permission compatibility can still resolve names,
                # but OP sync requires immutable Discord user/role IDs.
                level = self._resolver.resolve(
                    link.discord_user_id, role_ids, server_id,
                )
                if type(level) is not int or not -1 <= level <= 4:
                    return False
                if level > 0 or (level == 0 and self.config.allow_removals):
                    entries.append({
                        "minecraft_uuid": link.minecraft_uuid,
                        "minecraft_name": link.minecraft_name,
                        "level": level,
                    })
            if entries:
                entries_by_server[server_id] = entries
        if not entries_by_server:
            return False
        delivered = False
        for server_id, entries in entries_by_server.items():
            try:
                await self._gateway.send_packet(
                    server_id, "op_sync_apply", None, {
                        "entries": entries,
                        "allow_removals": self.config.allow_removals,
                    },
                )
                delivered = True
            except Exception:
                LOGGER.warning("DMCC OP synchronization unavailable for server=%s", server_id)
        return delivered

    def start(self) -> None:
        if self.config.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="dmcc-op-sync")

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                LOGGER.exception("DMCC OP synchronization failed")
            await asyncio.sleep(self.config.interval_seconds)

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
