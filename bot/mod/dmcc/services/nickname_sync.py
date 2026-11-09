"""bot/mod/dmcc/services/nickname_sync.py

Modification():

- Opt-in, permission-scoped Discord nickname synchronization for linked Minecraft users. Never edits a guild outside the configured guild, never edits bots, owners or members above the Bot role, and leaves unlinked users untouched unless rese
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from string import Formatter
from collections.abc import Mapping

LOGGER = logging.getLogger(__name__)
_ALLOWED = frozenset({"player_name", "discord_name"})


@dataclass(frozen=True, slots=True)
class NicknameSyncConfig:
    enabled: bool = False
    guild_id: str | None = None
    template: str = "[MC] {player_name}"
    reset_unlinked: bool = False
    sweep_interval_seconds: int = 3600
    max_sweep_per_cycle: int = 100

    @classmethod
    def from_mapping(cls, raw: object) -> "NicknameSyncConfig":
        if not isinstance(raw, Mapping) or set(raw) - {
            "enabled", "guild_id", "template", "reset_unlinked", "sweep_interval_seconds",
            "max_sweep_per_cycle",
        }:
            raise ValueError("nickname_sync must have documented fields")
        enabled, guild_id = raw.get("enabled", False), raw.get("guild_id")
        reset_unlinked = raw.get("reset_unlinked", False)
        if type(enabled) is not bool or type(reset_unlinked) is not bool:
            raise ValueError("nickname_sync flags must be booleans")
        if enabled and (
            not isinstance(guild_id, str) or not guild_id.isascii()
            or not guild_id.isdecimal() or not 15 <= len(guild_id) <= 20
        ):
            raise ValueError("nickname_sync.guild_id must be a Discord snowflake when enabled")
        if guild_id is not None and (
            not isinstance(guild_id, str) or not guild_id.isascii()
            or not guild_id.isdecimal() or not 15 <= len(guild_id) <= 20
        ):
            raise ValueError("nickname_sync.guild_id invalid")
        template = raw.get("template", "[MC] {player_name}")
        if not isinstance(template, str) or not template.strip() or len(template) > 32:
            raise ValueError("nickname_sync.template must be 1 to 32 characters")
        try:
            fields = [field for _, field, fmt, conv in Formatter().parse(template)
                      if field is not None and not fmt and not conv]
            all_fields = [field for _, field, _, _ in Formatter().parse(template)
                          if field is not None]
        except ValueError as exc:
            raise ValueError("invalid nickname_sync template braces") from exc
        if not fields or len(fields) != len(all_fields) or any(f not in _ALLOWED for f in fields):
            raise ValueError("nickname_sync template has invalid placeholders")
        interval = raw.get("sweep_interval_seconds", 3600)
        limit = raw.get("max_sweep_per_cycle", 100)
        if type(interval) is not int or not 300 <= interval <= 86400:
            raise ValueError("sweep_interval_seconds must be 300..86400")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("max_sweep_per_cycle must be 1..500")
        return cls(enabled, guild_id, template, reset_unlinked, interval, limit)


class NicknameSyncService:
    """Synchronize one scoped Discord guild without overwriting unrelated nicknames by default."""

    def __init__(self, bot: object, links: object, config: NicknameSyncConfig) -> None:
        self._bot, self._links, self.config = bot, links, config
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._sweep_cursor = 0

    def _guild(self):
        if not self.config.enabled or self.config.guild_id is None:
            return None
        get_guild = getattr(self._bot, "get_guild", None)
        return get_guild(int(self.config.guild_id)) if callable(get_guild) else None

    @staticmethod
    def _can_edit(guild: object, member: object) -> bool:
        me = getattr(guild, "me", None)
        perms = getattr(me, "guild_permissions", None)
        if (me is None or not getattr(perms, "manage_nicknames", False)
                or bool(getattr(member, "bot", False))
                or getattr(member, "id", None) == getattr(guild, "owner_id", None)):
            return False
        top = getattr(member, "top_role", None)
        own = getattr(me, "top_role", None)
        if top is None or own is None:
            return False
        try:
            return own > top
        except (TypeError, AttributeError):
            return False

    async def sync_user(self, discord_id: str, *, member: object | None = None) -> bool:
        guild = self._guild()
        if guild is None or self._closed:
            return False
        try:
            numeric_id = int(discord_id)
        except (TypeError, ValueError):
            return False
        target = member if member is not None and getattr(member, "guild", None) is guild else None
        if target is None:
            get_member = getattr(guild, "get_member", None)
            target = get_member(numeric_id) if callable(get_member) else None
        if target is None or getattr(target, "id", None) != numeric_id or not self._can_edit(guild, target):
            return False
        linked = self._links.links_for_discord(discord_id)
        if linked:
            # The most recently linked account is authoritative, as in upstream.
            player = linked[-1].minecraft_name[:16]
            discord_name = str(getattr(target, "name", ""))[:32]
            desired = self.config.template.format_map({
                "player_name": player, "discord_name": discord_name,
            })[:32]
        elif self.config.reset_unlinked:
            desired = None
        else:
            return False
        if getattr(target, "nick", None) == desired:
            return False
        try:
            await target.edit(nick=desired, reason="DMCC verified Minecraft account sync")
        except Exception:
            LOGGER.warning("DMCC nickname sync denied by Discord for user_id=%s", discord_id)
            return False
        return True

    async def sweep_once(self) -> int:
        guild = self._guild()
        if guild is None or self._closed:
            return 0
        members = list(getattr(guild, "members", ()))
        if not members:
            self._sweep_cursor = 0
            return 0
        start = self._sweep_cursor % len(members)
        count, batch_size = 0, min(len(members), self.config.max_sweep_per_cycle)
        self._sweep_cursor = (start + batch_size) % len(members)
        for offset in range(batch_size):
            member = members[(start + offset) % len(members)]
            if await self.sync_user(str(getattr(member, "id", "")), member=member):
                count += 1
        return count

    def start(self) -> None:
        if self.config.enabled and self._task is None and not self._closed:
            self._task = asyncio.create_task(self._loop(), name="dmcc-nickname-sync")

    async def _loop(self) -> None:
        while True:
            try:
                await self.sweep_once()
            except Exception:
                LOGGER.exception("DMCC nickname sweep failed")
            await asyncio.sleep(self.config.sweep_interval_seconds)

    async def close(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
