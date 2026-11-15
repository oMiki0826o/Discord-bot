"""tests/test_dmcc_proxy_whitelist.py
Optional Velocity global-whitelist routing stays outside backend servers.

Modification():
- Check Velocity whitelist routing.
"""
from __future__ import annotations

import asyncio

from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings
from bot.mod.dmcc.services.proxy_whitelist import ProxyWhitelistService


class Requests:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def request(self, server_id: str, packet_type: str, data: dict[str, object]):
        self.calls.append((server_id, packet_type, data))
        return {"ok": True, "output": "Proxy whitelist update requested for Steve."}


def test_proxy_whitelist_requires_a_bridge_enabled_velocity_target() -> None:
    raw = {
        **DEFAULT_SETTINGS,
        "servers": [{"server_id": "proxy", "bridge": {
            "enabled": True, "peer_kind": "velocity", "secret_env": "PROXY_BRIDGE_SECRET",
        }}],
        "proxy_whitelist": {"enabled": True, "server_id": "proxy"},
    }
    settings = DmccSettings.from_mapping(raw, environ={"PROXY_BRIDGE_SECRET": "test-secret"})
    assert settings.proxy_whitelist.enabled is True
    assert settings.proxy_whitelist.server_id == "proxy"

def test_proxy_whitelist_add_uses_only_the_proxy_protocol() -> None:
    async def check() -> None:
        requests = Requests()
        service = ProxyWhitelistService(requests, "proxy")
        assert await service.add("Steve") == "Proxy whitelist update requested for Steve."
        assert requests.calls == [(
            "proxy", "proxy_whitelist_request", {"action": "add", "player_name": "Steve"},
        )]
    asyncio.run(check())
