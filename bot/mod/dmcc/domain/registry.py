"""bot/mod/dmcc/domain/registry.py
Validated lookup of configured Minecraft servers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Iterable

from .capabilities import Capability
from .errors import CapabilityUnavailable, ServerNotFound
from .models import ManagedServer


class ServerRegistry:
    def __init__(self, servers: Iterable[ManagedServer]) -> None:
        indexed: dict[str, ManagedServer] = {}
        for server in servers:
            if not server.server_id.strip():
                raise ValueError("server_id must be non-empty")
            if server.server_id in indexed:
                raise ValueError(f"duplicate server_id: {server.server_id}")
            indexed[server.server_id] = server
        self._servers = indexed

    def get(self, server_id: str) -> ManagedServer:
        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise ServerNotFound(f"unknown server_id: {server_id}") from exc

    def all(self) -> tuple[ManagedServer, ...]:
        return tuple(self._servers.values())

    def require(self, server_id: str, capability: Capability) -> ManagedServer:
        server = self.get(server_id)
        if capability not in server.capabilities:
            raise CapabilityUnavailable(
                f"server {server_id} does not provide {capability.value} capability"
            )
        return server
