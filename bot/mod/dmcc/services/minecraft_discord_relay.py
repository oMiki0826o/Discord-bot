"""bot/mod/dmcc/services/minecraft_discord_relay.py
Route authenticated Minecraft chat events to their configured Discord channel.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Protocol

from ..events import MinecraftEvent
from ..repositories.state import JsonStateRepository


class DiscordMessageSender(Protocol):
    async def send_discord_message(self, channel_id: str, content: str) -> None: ...


class MinecraftDiscordRelayService:
    """Platform-neutral Minecraft-to-Discord relay; the Cog supplies the sender."""

    def __init__(self, state: JsonStateRepository, sender: DiscordMessageSender) -> None:
        self._state = state
        self._sender = sender

    async def forward(self, event: MinecraftEvent) -> bool:
        channel_id = self._state.channel_for_server(event.server_id)
        if channel_id is None:
            return False
        player_name = event.data.get("player_name")
        if event.type == "player_chat":
            message = event.data.get("message")
            if not isinstance(player_name, str) or not player_name.strip() or not isinstance(message, str) or not message.strip():
                return False
            content = f"<{player_name.strip()}> {message.strip()}"
        elif event.type == "player_join":
            if not isinstance(player_name, str) or not player_name.strip():
                return False
            content = f"**{player_name.strip()} joined the game**"
        elif event.type == "player_quit":
            if not isinstance(player_name, str) or not player_name.strip():
                return False
            content = f"**{player_name.strip()} left the game**"
        elif event.type == "server_started":
            content = "**Minecraft server started**"
        elif event.type == "server_stopping":
            content = "**Minecraft server stopping**"
        elif event.type == "player_gamemode":
            game_mode = event.data.get("game_mode")
            if not isinstance(player_name, str) or not player_name.strip() or not isinstance(game_mode, str) or not game_mode.strip():
                return False
            content = f"**{player_name.strip()} changed game mode to {game_mode.strip()}**"
        elif event.type == "player_death":
            death_message = event.data.get("death_message")
            if not isinstance(death_message, str) or not death_message.strip():
                return False
            content = f"**{death_message.strip()}**"
        elif event.type == "player_advancement":
            title = event.data.get("title")
            advancement_type = event.data.get("advancement_type")
            if not isinstance(player_name, str) or not player_name.strip() or not isinstance(title, str) or not title.strip():
                return False
            label = "challenge" if advancement_type == "challenge" else "goal" if advancement_type == "goal" else "advancement"
            content = f"**{player_name.strip()} has made the {label} [{title.strip()}]**"
        else:
            return False
        await self._sender.send_discord_message(channel_id, content)
        return True
