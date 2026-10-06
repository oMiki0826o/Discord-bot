"""bot/mod/dmcc/services/link_requests.py
Handle Minecraft-originated account-link requests without Discord imports.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Protocol

from ..events import MinecraftEvent
from .linking import LinkingService


class LinkResponseSender(Protocol):
    async def send_packet(
        self, server_id: str, packet_type: str, request_id: str | None, data: dict[str, object]
    ) -> None: ...


class LinkRequestHandler:
    """Generate a code only for a well-formed authenticated Bridge request."""

    def __init__(self, linking: LinkingService, sender: LinkResponseSender) -> None:
        self._linking = linking
        self._sender = sender

    async def handle(self, event: MinecraftEvent) -> None:
        if event.type == "unlink_request":
            await self._handle_unlink(event)
            return
        if event.type != "link_request":
            return
        request_id = event.data.get("request_id")
        minecraft_uuid = event.data.get("minecraft_uuid")
        minecraft_name = event.data.get("minecraft_name")
        if not all(isinstance(value, str) and value.strip() for value in (request_id, minecraft_uuid, minecraft_name)):
            return
        code = self._linking.begin_minecraft_link(minecraft_uuid, minecraft_name)
        await self._sender.send_packet(event.server_id, "link_response", request_id, {"code": code})

    async def _handle_unlink(self, event: MinecraftEvent) -> None:
        request_id = event.data.get("request_id")
        minecraft_uuid = event.data.get("minecraft_uuid")
        if not all(isinstance(value, str) and value.strip() for value in (request_id, minecraft_uuid)):
            return
        removed = self._linking.unlink_minecraft(minecraft_uuid)
        await self._sender.send_packet(event.server_id, "unlink_response", request_id, {"removed": removed})
