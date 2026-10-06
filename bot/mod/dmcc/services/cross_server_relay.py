"""bot/mod/dmcc/services/cross_server_relay.py
Optional, loop-free Minecraft chat relay between authenticated Bridge peers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..events import MinecraftEvent


class _MinecraftMessageSender(Protocol):
    async def send_minecraft_message(self, server_id: str, message: str) -> None: ...


class CrossServerRelayService:
    """Forward player-originated chat to other connected servers only.

    The Bridge renders inbound relay packets as system messages, which do not re-enter
    Minecraft's player-chat event.  This preserves a one-hop relay and prevents loops.
    """

    def __init__(
        self,
        gateway: _MinecraftMessageSender,
        online_server_ids: Callable[[], tuple[str, ...]],
    ) -> None:
        self._gateway = gateway
        self._online_server_ids = online_server_ids

    async def forward(self, event: MinecraftEvent) -> bool:
        """Relay one valid player chat event to every peer other than its source."""

        if event.type != "player_chat":
            return False
        player_name = event.data.get("player_name")
        message = event.data.get("message")
        if not isinstance(player_name, str) or not player_name.strip():
            return False
        if not isinstance(message, str) or not message.strip():
            return False
        payload = f"[{event.server_id}] <{player_name.strip()}> {message.strip()}"
        delivered = False
        for server_id in self._online_server_ids():
            if server_id == event.server_id:
                continue
            try:
                await self._gateway.send_minecraft_message(server_id, payload)
            except LookupError:
                continue
            delivered = True
        return delivered
