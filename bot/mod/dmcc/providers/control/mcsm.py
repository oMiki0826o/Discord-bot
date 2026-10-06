"""bot/mod/dmcc/providers/control/mcsm.py
Narrow MCSManager instance control adapter.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...domain.errors import ProviderConnectionError
from ...domain.models import ProcessState


class McsmControlProvider:
    def __init__(self, provider_id: str, client, daemon_id: str, instance_id: str) -> None:
        self.provider_id = provider_id
        self._client = client
        self._daemon_id = _identifier(daemon_id, "daemon")
        self._instance_id = _identifier(instance_id, "instance")

    def _params(self, target: str | None) -> dict[str, str]:
        return {"daemonId": self._daemon_id, "uuid": self._instance_id if target is None else _identifier(target, "instance")}

    async def status(self, target: str | None = None) -> ProcessState:
        response = await self._client.request_json("GET", "/api/instance", params=self._params(target), payload=None)
        _ensure_success(response)
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise ProviderConnectionError("invalid MCSManager status response")
        raw_status = data.get("status", data.get("instanceStatus"))
        states = {0: ProcessState.STOPPED, 1: ProcessState.STOPPING, 2: ProcessState.STARTING, 3: ProcessState.RUNNING, -1: ProcessState.UNKNOWN}
        if type(raw_status) is not int or raw_status not in states:
            raise ProviderConnectionError("invalid MCSManager status response")
        return states[raw_status]

    async def start(self, target: str | None = None) -> None:
        await self._action("open", target)

    async def stop(self, target: str | None = None) -> None:
        await self._action("stop", target)

    async def restart(self, target: str | None = None) -> None:
        await self._action("restart", target)

    async def kill(self, target: str | None = None) -> None:
        await self._action("kill", target)

    async def _action(self, action: str, target: str | None) -> None:
        response = await self._client.request_json("GET", f"/api/protected_instance/{action}", params=self._params(target), payload=None)
        _ensure_success(response)


def _ensure_success(response: Mapping[str, object]) -> None:
    if response.get("status") != 200:
        raise ProviderConnectionError("MCSManager API failed")


def _identifier(value: str, kind: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or ".." in value:
        raise ValueError(f"MCSManager {kind} identifier is invalid")
    return value
