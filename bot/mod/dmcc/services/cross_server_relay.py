"""bot/mod/dmcc/services/cross_server_relay.py
Optional, loop-free Minecraft chat relay between authenticated Bridge peers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..events import MinecraftEvent
from .v3_features import V3FeatureConfig
from .v3_minecraft import format_minecraft_message
from .rich_text import parse_discord_markdown


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
        *, event_types: frozenset[str] | set[str] = frozenset({"player_chat"}),
        features: V3FeatureConfig | None = None,
    ) -> None:
        self._gateway = gateway
        self._online_server_ids = online_server_ids
        self._event_types = frozenset(event_types)
        self._features = features or V3FeatureConfig()

    def apply_preview_features(self, features: V3FeatureConfig) -> None:
        self._features = features

    async def forward(self, event: MinecraftEvent) -> bool:
        """Relay one valid player chat event to every peer other than its source."""

        if event.type not in self._event_types:
            return False
        player_name = event.data.get("player_name")
        message = event.data.get("message")
        if event.type == "player_chat":
            if not isinstance(player_name, str) or not player_name.strip():
                return False
            if not isinstance(message, str) or not message.strip():
                return False
            payload = f"[{event.server_id}] <{player_name.strip()[:64]}> {message.strip()[:1200]}"
        else:
            label = {
                "player_join": "joined the game",
                "player_quit": "left the game",
                "player_gamemode": "changed game mode",
                "player_advancement": "made an advancement",
                "server_started": "server started",
                "server_stopping": "server stopping",
            }.get(event.type)
            if event.type == "server_broadcast":
                message = event.data.get("message")
                if not isinstance(message, str) or not message.strip():
                    return False
                payload = f"[{event.server_id}] {message.strip()[:1200]}"
            elif event.type == "player_death":
                message = event.data.get("death_message")
                if not isinstance(message, str) or not message.strip():
                    return False
                payload = f"[{event.server_id}] {message.strip()[:1000]}"
            elif label is None:
                return False
            elif event.type.startswith("player_"):
                if not isinstance(player_name, str) or not player_name.strip():
                    return False
                payload = f"[{event.server_id}] {player_name.strip()[:64]} {label}"
            else:
                payload = f"[{event.server_id}] {label}"
        if self._features.enabled and event.type in {"player_chat", "server_broadcast"}:
            flags = self._features.parsing["minecraft_to_minecraft"]
            payload = format_minecraft_message(
                payload,
                emoji_aliases=self._features.minecraft_emoji_aliases,
                mention_ids=self._features.minecraft_mention_ids,
                custom_emojis=flags["custom_emojis"],
                mentions=flags["mentions"],
                unicode_emojis=flags["unicode_emojis"],
                timestamps=flags["timestamps"],
                markdown=flags["markdown"],
                hyperlinks=flags["hyperlinks"],
            )
        delivered = False
        for server_id in self._online_server_ids():
            if server_id == event.server_id:
                continue
            try:
                if (self._features.enabled and event.type in {"player_chat", "server_broadcast"}
                        and self._features.allows("minecraft_to_minecraft", "markdown")
                        and hasattr(self._gateway, "send_minecraft_segments")):
                    await self._gateway.send_minecraft_segments(
                        server_id, parse_discord_markdown(payload),
                    )
                else:
                    await self._gateway.send_minecraft_message(server_id, payload)
            except LookupError:
                continue
            delivered = True
        return delivered
