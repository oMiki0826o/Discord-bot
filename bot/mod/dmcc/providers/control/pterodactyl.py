"""bot/mod/dmcc/providers/control/pterodactyl.py
Narrow Pterodactyl Client API control adapter.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...domain.errors import ProviderConnectionError
from ...domain.models import ProcessState


_STATES = {
    "running": ProcessState.RUNNING,
    "offline": ProcessState.STOPPED,
    "starting": ProcessState.STARTING,
    "stopping": ProcessState.STOPPING,
}


class PterodactylControlProvider:
    def __init__(self, provider_id: str, client, server_identifier: str) -> None:
        self.provider_id = provider_id
        self._client = client
        self._server_identifier = _identifier(server_identifier)

    def _target(self, target: str | None) -> str:
        return self._server_identifier if target is None else _identifier(target)

    async def status(self, target: str | None = None) -> ProcessState:
        response = await self._client.request_json(
            "GET", f"/api/client/servers/{self._target(target)}/resources", params={}, payload=None
        )
        attributes = response.get("attributes")
        state = attributes.get("current_state") if isinstance(attributes, Mapping) else None
        result = _STATES.get(state)
        if result is None:
            raise ProviderConnectionError("unsupported Pterodactyl status response")
        return result

    async def start(self, target: str | None = None) -> None:
        await self._power(self._target(target), "start")

    async def stop(self, target: str | None = None) -> None:
        await self._power(self._target(target), "stop")

    async def restart(self, target: str | None = None) -> None:
        await self._power(self._target(target), "restart")

    async def kill(self, target: str | None = None) -> None:
        await self._power(self._target(target), "kill")

    async def _power(self, server_identifier: str, signal: str) -> None:
        await self._client.request_json(
            "POST", f"/api/client/servers/{server_identifier}/power", params={}, payload={"signal": signal}
        )


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or ".." in value:
        raise ValueError("Pterodactyl server identifier is invalid")
    return value
