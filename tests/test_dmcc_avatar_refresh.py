"""Avatar refresh prefers a genuine proxy connection over backend hops."""
from __future__ import annotations

import asyncio

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.avatar_refresh import AvatarRefreshService


class Probe:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def image_exists(self, url: str) -> bool:
        self.urls.append(url)
        return "mc-heads.net" in url


def test_velocity_mode_refreshes_only_on_proxy_login() -> None:
    async def check() -> None:
        probe = Probe()
        service = AvatarRefreshService(
            enabled=True, source="velocity", source_server_id="proxy",
            cache_ttl_seconds=600, probe=probe,
        )
        event = MinecraftEvent("proxy_player_login", "proxy", {
            "minecraft_uuid": "123e4567-e89b-12d3-a456-426614174000", "player_name": "Steve",
        })
        await service.observe(event)
        assert service.cached_url(event.data["minecraft_uuid"]) == (
            "https://mc-heads.net/avatar/123e4567-e89b-12d3-a456-426614174000/64"
        )
        assert len(probe.urls) == 1
        await service.observe(MinecraftEvent("player_join", "survival", event.data))
        assert len(probe.urls) == 1
    asyncio.run(check())


def test_fabric_mode_revalidates_on_each_real_player_join() -> None:
    async def check() -> None:
        probe = Probe()
        service = AvatarRefreshService(
            enabled=True, source="fabric", cache_ttl_seconds=86_400, probe=probe,
        )
        event = MinecraftEvent("player_join", "survival", {
            "minecraft_uuid": "123e4567-e89b-12d3-a456-426614174000", "player_name": "Steve",
        })
        await service.observe(event)
        await service.observe(event)
        assert len(probe.urls) == 2
        await service.observe(MinecraftEvent("proxy_player_login", "proxy", event.data))
        assert len(probe.urls) == 2
    asyncio.run(check())
