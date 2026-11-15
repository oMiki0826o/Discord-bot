"""bot/mod/dmcc/services/link_requests.py
Handle Minecraft-originated account-link requests without Discord imports.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID
import re

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
        if event.type == "link_status_request":
            await self._handle_link_status(event)
            return
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

    async def _handle_link_status(self, event: MinecraftEvent) -> None:
        """Authenticated server-side link check; never includes Discord account IDs."""
        request_id = event.data.get("request_id")
        minecraft_uuid = event.data.get("minecraft_uuid")
        minecraft_name = event.data.get("minecraft_name")
        if (
            not isinstance(request_id, str) or not request_id.strip()
            or not isinstance(minecraft_uuid, str)
            or not isinstance(minecraft_name, str)
            or not re.fullmatch(r"[A-Za-z0-9_]{3,16}", minecraft_name)
        ):
            return
        try:
            parsed = UUID(minecraft_uuid)
        except (TypeError, ValueError, AttributeError):
            return
        if parsed.int == 0 or str(parsed) != minecraft_uuid.lower():
            return
        linked = self._linking.is_minecraft_linked(minecraft_uuid)
        data: dict[str, object] = {"minecraft_uuid": minecraft_uuid, "linked": linked}
        if not linked:
            data["code"] = self._linking.begin_minecraft_link(minecraft_uuid, minecraft_name)
        await self._sender.send_packet(
            event.server_id, "link_status_response", request_id, data,
        )

    async def _handle_unlink(self, event: MinecraftEvent) -> None:
        request_id = event.data.get("request_id")
        minecraft_uuid = event.data.get("minecraft_uuid")
        if not all(isinstance(value, str) and value.strip() for value in (request_id, minecraft_uuid)):
            return
        removed = self._linking.unlink_minecraft(minecraft_uuid)
        await self._sender.send_packet(event.server_id, "unlink_response", request_id, {"removed": removed})
