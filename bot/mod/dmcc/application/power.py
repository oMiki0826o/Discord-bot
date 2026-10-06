"""bot/mod/dmcc/application/power.py
Authorized start, stop, restart, and explicit kill dispatch.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.capabilities import Capability
from ..domain.errors import (
    AuthorizationError,
    OperationTimeout,
    ProviderConfigurationError,
    ProviderConnectionError,
)
from ..domain.models import PowerAction
from ..domain.ports import ServerControlPort
from ..domain.registry import ServerRegistry


class PowerService:
    def __init__(
        self,
        servers: ServerRegistry,
        controls: Mapping[str, ServerControlPort],
    ) -> None:
        self._servers = servers
        self._controls = controls

    async def execute(
        self,
        server_id: str,
        action: PowerAction,
        *,
        actor_level: int,
    ) -> None:
        if actor_level < 4:
            raise AuthorizationError("power operation requires DMCC level 4")
        required = Capability.KILL if action is PowerAction.KILL else Capability.CONTROL
        server = self._servers.require(server_id, required)
        assert server.control_provider_id is not None
        provider = self._controls.get(server.control_provider_id)
        if provider is None:
            raise ProviderConfigurationError(
                f"control provider is not loaded: {server.control_provider_id}"
            )
        try:
            if action is PowerAction.START:
                await provider.start(server.control_target)
            elif action is PowerAction.STOP:
                await provider.stop(server.control_target)
            elif action is PowerAction.RESTART:
                await provider.restart(server.control_target)
            else:
                await provider.kill(server.control_target)
        except TimeoutError as exc:
            raise OperationTimeout(f"{action.value} timed out for server {server_id}") from exc
        except (ConnectionError, OSError) as exc:
            raise ProviderConnectionError(
                f"control provider unavailable for server {server_id}"
            ) from exc
