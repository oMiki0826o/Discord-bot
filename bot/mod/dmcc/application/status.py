"""bot/mod/dmcc/application/status.py
Composite Bridge and process status queries.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ..domain.errors import OperationTimeout, ProviderConfigurationError, ProviderConnectionError
from ..domain.models import BridgeState, ProcessState, ServerStatus
from ..domain.ports import ServerControlPort
from ..domain.registry import ServerRegistry


class BridgeQueryPort(Protocol):
    def is_connected(self, server_id: str) -> bool: ...


class StatusQueryService:
    def __init__(
        self,
        servers: ServerRegistry,
        bridge: BridgeQueryPort,
        controls: Mapping[str, ServerControlPort],
    ) -> None:
        self._servers = servers
        self._bridge = bridge
        self._controls = controls

    async def get(self, server_id: str) -> ServerStatus:
        server = self._servers.get(server_id)
        bridge_state = BridgeState.UNSUPPORTED
        if server.bridge_enabled:
            bridge_state = (
                BridgeState.CONNECTED
                if self._bridge.is_connected(server_id)
                else BridgeState.DISCONNECTED
            )
        process_state = ProcessState.UNKNOWN
        if server.control_provider_id is not None:
            provider = self._controls.get(server.control_provider_id)
            if provider is None:
                raise ProviderConfigurationError(
                    f"control provider is not loaded: {server.control_provider_id}"
                )
            try:
                process_state = await provider.status(server.control_target)
            except TimeoutError as exc:
                raise OperationTimeout(f"status timed out for server {server_id}") from exc
            except (ConnectionError, OSError) as exc:
                raise ProviderConnectionError(
                    f"control provider unavailable for server {server_id}"
                ) from exc
        return ServerStatus(server_id, bridge_state, process_state)
