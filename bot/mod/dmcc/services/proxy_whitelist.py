"""Optional typed relay for the local Velocity global-whitelist companion."""

from __future__ import annotations

from typing import Protocol

from .whitelist import whitelist_add_command


class ProxyWhitelistRequestPort(Protocol):
    async def request(
        self, server_id: str, packet_type: str, data: dict[str, object],
    ) -> dict[str, object]: ...


class ProxyWhitelistService:
    """Route allow-list changes to Velocity, never to one backend server."""

    def __init__(self, requests: ProxyWhitelistRequestPort, server_id: str | None) -> None:
        self._requests = requests
        self._server_id = server_id

    @property
    def enabled(self) -> bool:
        return self._server_id is not None

    @property
    def server_id(self) -> str | None:
        """The permission scope required for a global proxy mutation."""
        return self._server_id

    async def add(self, player_name: str) -> str:
        # Share the Java-edition name validation used by the regular command.
        whitelist_add_command(player_name)
        if self._server_id is None:
            raise LookupError("proxy whitelist is disabled")
        response = await self._requests.request(
            self._server_id,
            "proxy_whitelist_request",
            {"action": "add", "player_name": player_name},
        )
        if response.get("ok") is not True:
            raise RuntimeError(str(response.get("error", "proxy whitelist rejected the request")))
        return str(response.get("output", "Proxy whitelist updated."))
