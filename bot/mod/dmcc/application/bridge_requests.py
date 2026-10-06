"""bot/mod/dmcc/application/bridge_requests.py
Typed Bridge request use cases shared by Discord adapters.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class RequestPort(Protocol):
    async def request(
        self,
        server_id: str,
        packet_type: str,
        data: dict[str, object],
    ) -> dict[str, object]: ...


class BridgeRequestService:
    def __init__(self, requests: RequestPort) -> None:
        self._requests = requests

    async def server_info(self, server_id: str) -> dict[str, object]:
        return await self._requests.request(server_id, "server_info_request", {})

    async def execute(self, server_id: str, command: str, op_level: int) -> str:
        response = await self._requests.request(
            server_id,
            "command_request",
            {"command": command, "op_level": max(0, op_level)},
        )
        return str(response.get("output", ""))

    async def log(self, server_id: str) -> Mapping[str, object]:
        return await self._requests.request(server_id, "log_request", {"name": "latest.log"})

    async def stats(
        self,
        server_id: str,
        stat_type: str,
        stat: str,
    ) -> dict[str, object]:
        return await self._requests.request(
            server_id,
            "stats_request",
            {"stat_type": stat_type, "stat": stat},
        )
