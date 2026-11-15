"""Bounded, opt-in Minecraft avatar URL verification with stable fallbacks."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from ..events import MinecraftEvent


class AvatarProbe(Protocol):
    async def image_exists(self, url: str) -> bool: ...


class AiohttpAvatarProbe:
    """Probe only fixed HTTPS avatar endpoints; never accepts user-provided URLs."""

    async def image_exists(self, url: str) -> bool:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"Range": "bytes=0-0"}) as response:
                    return response.status == 200 and response.headers.get("Content-Type", "").startswith("image/")
        except (aiohttp.ClientError, TimeoutError):
            return False


@dataclass(frozen=True, slots=True)
class _Entry:
    url: str | None
    expires_at: float


class AvatarRefreshService:
    """Use exactly one configured event source, never a priority race."""

    def __init__(
        self, *, enabled: bool, source: str = "fabric", source_server_id: str | None = None,
        cache_ttl_seconds: int = 21_600,
        probe: AvatarProbe | None = None, clock=time.monotonic,
    ) -> None:
        self._enabled = enabled
        if source not in {"fabric", "velocity"}:
            raise ValueError("avatar source must be fabric or velocity")
        if source == "velocity" and (not isinstance(source_server_id, str) or not source_server_id.strip()):
            raise ValueError("velocity avatar source requires a server ID")
        self._source = source
        self._source_server_id = source_server_id
        self._ttl = cache_ttl_seconds
        self._probe = probe or AiohttpAvatarProbe()
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def observe(self, event: MinecraftEvent) -> None:
        if not self._enabled:
            return
        raw_uuid = event.data.get("minecraft_uuid")
        if not isinstance(raw_uuid, str):
            return
        try:
            player_uuid = str(uuid.UUID(raw_uuid))
        except ValueError:
            return
        if (
            event.type == "proxy_player_login" and self._source == "velocity"
            and event.server_id == self._source_server_id
        ):
            await self._refresh(player_uuid, force=True)
        elif event.type == "player_join" and self._source == "fabric":
            # A Fabric player_join is a real server login in the non-proxy
            # deployment.  Revalidate here so a changed skin is reflected on
            # the next login; backend transfer suppression belongs to the
            # Velocity deployment path above.
            await self._refresh(player_uuid, force=True)

    def cached_url(self, raw_uuid: object) -> str | None:
        if not isinstance(raw_uuid, str):
            return None
        try:
            key = str(uuid.UUID(raw_uuid))
        except ValueError:
            return None
        entry = self._entries.get(key)
        if entry is None or entry.expires_at <= self._clock():
            return None
        return entry.url

    async def _refresh(self, player_uuid: str, *, force: bool) -> None:
        existing = self._entries.get(player_uuid)
        if not force and existing is not None and existing.expires_at > self._clock():
            return
        lock = self._locks.setdefault(player_uuid, asyncio.Lock())
        async with lock:
            existing = self._entries.get(player_uuid)
            if not force and existing is not None and existing.expires_at > self._clock():
                return
            candidates = (
                f"https://mc-heads.net/avatar/{player_uuid}/64",
                f"https://crafatar.com/avatars/{player_uuid}?overlay",
            )
            selected = None
            for url in candidates:
                if await self._probe.image_exists(url):
                    selected = url
                    break
            self._entries[player_uuid] = _Entry(selected, self._clock() + self._ttl)
