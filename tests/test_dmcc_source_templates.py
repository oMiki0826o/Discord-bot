"""tests/test_dmcc_source_templates.py

Modification():

- Verify isolated upstream public-source templates, routes and privacy filters.
"""
from __future__ import annotations

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.presentation import PresentationSettings, render_message


def test_upstream_source_tellraw_routes_independently():
    settings = PresentationSettings.from_mapping({
        "servers": {"survival": {
            "label": "Survival",
            "event_channels": {"source_tell_raw": "123456789012345678"},
            "templates": {
                "source_tell_raw": "[{server}] /tellraw from {player}: {message}",
            },
        }},
    })
    profile = settings.servers["survival"]
    out = render_message(MinecraftEvent("server_broadcast", "survival", {
        "source_event": "tell_raw",
        "player_name": "Server",
        "message": "hello",
    }), profile, "111111111111111111")
    assert out is not None
    assert out.channel_id == "123456789012345678"
    assert out.content == "[Survival] /tellraw from Server: hello"


def test_private_source_msg_never_enters_public_discord_channels():
    settings = PresentationSettings.from_mapping({
        "servers": {"survival": {"templates": {"source_msg": "{message}"}}},
    })
    profile = settings.servers["survival"]
    blocked = render_message(MinecraftEvent("server_broadcast", "survival", {
        "source_event": "msg",
        "message": "secret",
        "player_name": "Steve",
    }), profile, "111111111111111111")
    assert blocked is None
    all_players = render_message(MinecraftEvent("server_broadcast", "survival", {
        "source_event": "msg", "public_broadcast": True,
        "message": "announcement", "player_name": "Steve",
    }), profile, "111111111111111111")
    assert all_players is not None
