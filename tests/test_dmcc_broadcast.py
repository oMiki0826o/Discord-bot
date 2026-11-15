"""tests/test_dmcc_broadcast.py

Modification():

- Capture public Minecraft command broadcasts without treating private commands as chat.
"""
from __future__ import annotations

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.presentation import PresentationSettings, render_message


def test_safe_public_broadcast_to_configured_discord_channel() -> None:
    profile = PresentationSettings.from_mapping({
        "servers": {"survival": {
            "label": "生存服",
            "templates": {"server_broadcast": "[公告] {player}: {message}"},
        }},
    }).servers["survival"]
    event = MinecraftEvent("server_broadcast", "survival", {
        "player_name": "Server", "message": "Restart in 5 minutes",
    })
    payload = render_message(event, profile, "123456789012345678")
    assert payload is not None
    assert payload.content == "[公告] Server: Restart in 5 minutes"


def test_empty_server_broadcast_is_ignored() -> None:
    profile = PresentationSettings.from_mapping({
        "servers": {"survival": {"label": "生存服"}},
    }).servers["survival"]
    event = MinecraftEvent("server_broadcast", "survival", {"message": ""})
    assert render_message(event, profile, "123") is None
