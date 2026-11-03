"""bot/mod/dmcc/services/mod_updates.py

Modification():

- Check explicitly mapped Fabric mods for compatible Modrinth updates.
- Bound network I/O and prevent untrusted destinations, spam, and unverified update claims.

"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
import json
import logging
import re

from ..events import MinecraftEvent

LOGGER = logging.getLogger(__name__)
_PROJECT = re.compile(r"^[A-Za-z0-9_-]{2,64}$")
_MOD_ID = re.compile(r"^[a-z0-9_.-]{2,64}$")
_MINECRAFT_VERSION = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")


@dataclass(frozen=True, slots=True)
class UpdateTarget:
    channel_id: str
    minecraft_version: str
    projects: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ModUpdateConfig:
    enabled: bool = False
    interval_seconds: int = 3600
    servers: Mapping[str, UpdateTarget] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: object, server_ids: set[str]) -> "ModUpdateConfig":
        if not isinstance(raw, Mapping) or set(raw) - {"enabled", "interval_seconds", "servers"}:
            raise ValueError("mod_updates must contain only enabled, interval_seconds, servers")
        enabled = raw.get("enabled", False)
        interval = raw.get("interval_seconds", 3600)
        if type(enabled) is not bool or type(interval) is not int or not 1800 <= interval <= 86400:
            raise ValueError("invalid mod_updates enabled or interval_seconds")
        definitions = raw.get("servers", {})
        if not isinstance(definitions, Mapping):
            raise ValueError("mod_updates.servers must be an object")
        targets = {}
        for server_id, opts in definitions.items():
            if server_id not in server_ids or not isinstance(opts, Mapping) or set(opts) - {
                "channel_id", "minecraft_version", "projects"
            }:
                raise ValueError("invalid mod_updates server config")
            channel_id, version, projects = opts.get("channel_id"), opts.get("minecraft_version"), opts.get("projects")
            if not isinstance(channel_id, str) or not channel_id.isascii() or not channel_id.isdecimal() or not 15 <= len(channel_id) <= 20:
                raise ValueError("invalid mod_updates channel_id")
            if not isinstance(version, str) or not _MINECRAFT_VERSION.fullmatch(version):
                raise ValueError("invalid mod_updates minecraft_version")
            if not isinstance(projects, Mapping) or not 1 <= len(projects) <= 32:
                raise ValueError("mod_updates.projects must list 1 to 32 Modrinth mappings")
            if not all(
                isinstance(mod_id, str) and _MOD_ID.fullmatch(mod_id)
                and isinstance(project, str) and _PROJECT.fullmatch(project)
                for mod_id, project in projects.items()
            ):
                raise ValueError("mod_updates project mappings require safe Modrinth IDs and Fabric mod IDs")
            targets[server_id] = UpdateTarget(channel_id, version, dict(projects))
        if len(targets) > 16:
            raise ValueError("too many mod_updates servers")
        return cls(enabled, interval, targets)


class ModUpdateService:
    def __init__(
        self,
        config: ModUpdateConfig,
        sender: object,
        *,
        fetch_versions: Callable[[str, str], Awaitable[list[dict]]] | None = None,
        connection_manager: object | None = None,
    ) -> None:
        self.config = config
        self._sender = sender
        self._connection_manager = connection_manager
        self._fetch_versions = fetch_versions or _fetch_modrinth
        self._inventory: dict[str, tuple[str, dict[str, str]]] = {}
        self._seen: set[tuple[str, str, str]] = set()
        self._task: asyncio.Task[None] | None = None

    async def on_event(self, event: MinecraftEvent) -> None:
        if not self.config.enabled or event.type != "server_started" or event.server_id not in self.config.servers:
            return
        version = event.data.get("minecraft_version")
        inventory = event.data.get("mods")
        if not isinstance(version, str) or not isinstance(inventory, list) or len(inventory) > 1000:
            return
        mods = {}
        for item in inventory:
            if not isinstance(item, Mapping):
                continue
            mod_id, version_number = item.get("mod_id"), item.get("version")
            if isinstance(mod_id, str) and isinstance(version_number, str) and _MOD_ID.fullmatch(mod_id) and 0 < len(version_number) <= 100:
                mods[mod_id] = version_number
        self._inventory[event.server_id] = (version, mods)

    def start(self) -> None:
        if self.config.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="dmcc-mod-updates")

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                LOGGER.exception("DMCC mod update cycle failed")
            await asyncio.sleep(self.config.interval_seconds)

    async def run_once(self) -> None:
        if not self.config.enabled:
            return
        for server_id, target in self.config.servers.items():
            if (
                self._connection_manager is not None
                and self._connection_manager.get(server_id) is None
            ):
                continue
            snapshot = self._inventory.get(server_id)
            if snapshot is None or snapshot[0] != target.minecraft_version:
                continue
            installed = snapshot[1]
            for mod_id, project in target.projects.items():
                current = installed.get(mod_id)
                if current is None:
                    continue
                try:
                    versions = await self._fetch_versions(project, target.minecraft_version)
                    # The Modrinth versions endpoint orders releases newest first. We
                    # require the currently installed version to exist in this list;
                    # unrecognized custom builds are not treated as outdated.
                    compatible = [
                        v["version_number"]
                        for v in versions
                        if isinstance(v, dict)
                        and isinstance(v.get("version_number"), str)
                        and target.minecraft_version in v.get("game_versions", [])
                        and "fabric" in v.get("loaders", [])
                    ]
                    if current not in compatible or compatible.index(current) == 0:
                        continue
                    newest = compatible[0]
                    marker = (server_id, mod_id, newest)
                    if marker in self._seen:
                        continue
                    await self._sender.send_discord_message(
                        target.channel_id,
                        f"**[{server_id}] 模組更新：{mod_id} {current} → {newest}**（Modrinth 專案 {project}）",
                    )
                    self._seen.add(marker)
                except Exception:
                    LOGGER.warning("DMCC update check failed for mod %s on %s", mod_id, server_id)

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def _fetch_modrinth(project: str, minecraft_version: str) -> list[dict]:
    """Fixed HTTPS host and no redirects; rejects oversized or malformed responses."""
    import aiohttp

    url = f"https://api.modrinth.com/v2/project/{project}/version"
    params = {
        "loaders": '["fabric"]',
        "game_versions": json.dumps([minecraft_version]),
    }
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(
        headers={"User-Agent": "MinecraftBridge/0.2.4 (Discord-bot)"}, timeout=timeout
    ) as session:
        async with session.get(url, params=params, allow_redirects=False) as response:
            if response.status != 200:
                raise RuntimeError("Modrinth API unavailable")
            payload = await response.content.read(524289)
            if len(payload) > 524288:
                raise ValueError("Modrinth response too large")
            data = json.loads(payload)
            if not isinstance(data, list):
                raise ValueError("Malformed Modrinth response")
            return data[:128]
