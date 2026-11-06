"""bot/mod/dmcc/services/minecraft_discord_relay.py

Modification():

- Preserve legacy relay behavior while supporting Minecraft presentation routing.

Authenticated Minecraft events to Discord.

The legacy one-channel Bot route remains intact unless a server explicitly
opts into a presentation profile. No Discord API calls occur in this service.
"""
from __future__ import annotations

from typing import Protocol

from ..events import MinecraftEvent
from ..repositories.state import JsonStateRepository
from .presentation import OutboundDiscordMessage, PresentationSettings, render_message
from .public_commands import sanitize_public_player_command


class DiscordMessageSender(Protocol):
    async def send_discord_message(self, channel_id: str, content: str) -> None: ...


class MinecraftDiscordRelayService:
    """Route validated events using configured Bot/Webhook presentation."""

    def __init__(
        self,
        state: JsonStateRepository,
        sender: DiscordMessageSender,
        presentation: PresentationSettings | None = None,
    ) -> None:
        self._state = state
        self._sender = sender
        self._presentation = presentation or PresentationSettings.empty()

    async def forward(self, event: MinecraftEvent) -> bool:
        channel_id = self._state.channel_for_server(event.server_id)
        profile = self._presentation.servers.get(event.server_id)
        if profile is not None:
            payload = render_message(event, profile, channel_id)
            if payload is None:
                return False
            await self._deliver(payload)
            return True

        # Old settings and existing $dmcc map commands retain exact behavior.
        if channel_id is None:
            return False
        content = _legacy_content(event)
        if content is None:
            return False
        await self._sender.send_discord_message(channel_id, content)
        return True

    async def _deliver(self, payload: OutboundDiscordMessage) -> None:
        send = getattr(self._sender, "send_discord_payload", None)
        if send is not None:
            await send(payload)
        else:
            # Minimal legacy adapters can still display text.
            await self._sender.send_discord_message(payload.channel_id, payload.content)


def _legacy_content(event: MinecraftEvent) -> str | None:
    player_name = event.data.get("player_name")
    if event.type == "player_command":
        command = sanitize_public_player_command(event.data.get("message"))
        if not command or not isinstance(player_name, str) or not player_name.strip():
            return None
        return f"**[{event.server_id}] {player_name.strip()[:64]} executed {command}**"
    if event.type == "server_broadcast":
        raw = event.data.get("message")
        if not isinstance(raw, str) or not raw.strip():
            return None
        source = event.data.get("player_name")
        source = source.strip()[:64] if isinstance(source, str) and source.strip() else "Server"
        return f"**[{event.server_id}] {source}: {raw.strip()[:1500]}**"
    if event.type == "player_chat":
        message = event.data.get("message")
        if not isinstance(player_name, str) or not player_name.strip() or not isinstance(message, str) or not message.strip():
            return None
        return f"<{player_name.strip()}> {message.strip()}"
    if event.type == "player_join":
        if not isinstance(player_name, str) or not player_name.strip():
            return None
        return f"**{player_name.strip()} joined the game**"
    if event.type == "player_quit":
        if not isinstance(player_name, str) or not player_name.strip():
            return None
        return f"**{player_name.strip()} left the game**"
    if event.type == "server_started":
        return "**Minecraft server started**"
    if event.type == "server_stopping":
        return "**Minecraft server stopping**"
    if event.type == "player_gamemode":
        game_mode = event.data.get("game_mode")
        if not isinstance(player_name, str) or not player_name.strip() or not isinstance(game_mode, str) or not game_mode.strip():
            return None
        return f"**{player_name.strip()} changed game mode to {game_mode.strip()}**"
    if event.type == "player_death":
        death_message = event.data.get("death_message")
        if not isinstance(death_message, str) or not death_message.strip():
            return None
        return f"**{death_message.strip()}**"
    if event.type == "player_advancement":
        title = event.data.get("title")
        advancement_type = event.data.get("advancement_type")
        if not isinstance(player_name, str) or not player_name.strip() or not isinstance(title, str) or not title.strip():
            return None
        label = "challenge" if advancement_type == "challenge" else "goal" if advancement_type == "goal" else "advancement"
        return f"**{player_name.strip()} has made the {label} [{title.strip()}]**"
    return None
