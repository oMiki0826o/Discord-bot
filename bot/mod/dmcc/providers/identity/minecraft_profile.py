"""bot/mod/dmcc/providers/identity/minecraft_profile.py
Bounded Minecraft profile lookups through a supplied JSON transport.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from ...domain.errors import ProviderConnectionError


@dataclass(frozen=True, slots=True)
class MinecraftProfile:
    uuid: str
    name: str


class MinecraftProfileProvider:
    def __init__(self, client, *, ttl_seconds: float = 300.0, max_entries: int = 256) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("profile cache limits must be positive")
        self._client = client
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._cache: dict[str, tuple[float, MinecraftProfile]] = {}

    async def lookup_name(self, name: str) -> MinecraftProfile:
        if not isinstance(name, str) or not name or len(name) > 16:
            raise ValueError("Minecraft name is invalid")
        key = "name:" + name.lower()
        cached = self._cached(key)
        if cached is not None:
            return cached
        return self._record(key, await self._lookup(f"/users/profiles/minecraft/{name}"))

    async def lookup_uuid(self, raw_uuid: str) -> MinecraftProfile:
        try:
            canonical = str(uuid.UUID(raw_uuid))
        except (ValueError, AttributeError) as exc:
            raise ValueError("Minecraft UUID is invalid") from exc
        key = "uuid:" + canonical
        cached = self._cached(key)
        if cached is not None:
            return cached
        return self._record(key, await self._lookup(f"/session/minecraft/profile/{canonical.replace('-', '')}"))

    async def _lookup(self, path: str) -> MinecraftProfile:
        try:
            response = await self._client.request_json("GET", path, params={}, payload=None)
            raw_uuid, name = response.get("id"), response.get("name")
            if not isinstance(raw_uuid, str) or not isinstance(name, str) or not name:
                raise ValueError
            return MinecraftProfile(str(uuid.UUID(raw_uuid)), name)
        except (ValueError, ProviderConnectionError) as exc:
            if isinstance(exc, ProviderConnectionError):
                raise
            raise ProviderConnectionError("invalid Minecraft profile response") from exc

    def _cached(self, key: str) -> MinecraftProfile | None:
        cached = self._cache.get(key)
        if cached is None or cached[0] <= time.monotonic():
            self._cache.pop(key, None)
            return None
        return cached[1]

    def _record(self, key: str, profile: MinecraftProfile) -> MinecraftProfile:
        if len(self._cache) >= self._max_entries:
            self._cache.pop(next(iter(self._cache)))
        expiry = time.monotonic() + self._ttl
        self._cache[key] = (expiry, profile)
        self._cache["uuid:" + profile.uuid] = (expiry, profile)
        self._cache["name:" + profile.name.lower()] = (expiry, profile)
        return profile
