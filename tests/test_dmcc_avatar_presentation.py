"""tests/test_dmcc_avatar_presentation.py

Modification():

- Verify safe player/event avatar selection and Webhook presentation parity.

"""
from __future__ import annotations

import pytest

from bot.mod.dmcc.services.presentation import PresentationError, PresentationSettings, render_message
from bot.mod.dmcc.events import MinecraftEvent


URL = "https://discord.com/api/webhooks/123456789012345678/test_token"


def _profile(**config):
    settings = PresentationSettings.from_mapping({
        "servers": {"survival": {
            "chat": {"mode": "webhook", "webhook_url_env": "TEST_WEBHOOK"},
            **config,
        }},
    }, environ={"TEST_WEBHOOK": URL})
    return settings.servers["survival"]


def test_player_head_uses_uuid_then_name_fallback():
    event = MinecraftEvent("player_chat", "survival", {
        "player_name": "Steve", "message": "hello",
    })
    payload = render_message(event, _profile(), "123")
    assert payload is not None
    assert payload.avatar_url == "https://mc-heads.net/avatar/Steve/64"


def test_own_discord_event_logo_is_independent_from_player_avatar():
    event = MinecraftEvent("player_join", "survival", {"player_name": "Steve"})
    profile = _profile(events={
        "mode": "webhook", "webhook_url_env": "TEST_WEBHOOK",
        "username": "KunlunSMP🌸", "avatar_url": "https://cdn.discordapp.com/avatars/123/abc.png",
    })
    payload = render_message(event, profile, "123")
    assert payload is not None
    assert payload.avatar_url == "https://cdn.discordapp.com/avatars/123/abc.png"
    assert payload.username == "KunlunSMP🌸"


def test_chat_avatar_template_uses_validated_uuid_placeholder():
    event = MinecraftEvent("player_chat", "survival", {
        "player_name": "Steve", "message": "hello",
        "minecraft_uuid": "123e4567-e89b-12d3-a456-426614174000",
    })
    profile = _profile(chat={
        "mode": "webhook", "webhook_url_env": "TEST_WEBHOOK",
        "avatar_url": "https://mc-heads.net/avatar/{minecraft_uuid}/64",
    })
    payload = render_message(event, profile, "123")
    assert payload is not None
    assert payload.avatar_url == "https://mc-heads.net/avatar/123e4567-e89b-12d3-a456-426614174000/64"


@pytest.mark.parametrize("avatar", [
    "http://mc-heads.net/avatar/Steve",
    "https://evil.test/avatar/{player}",
    "https://mc-heads.net@evil.test/avatar/{player}",
    "https://mc-heads.net/avatar/{player.__class__}",
    "https://mc-heads.net/avatar/{player}?secret=x",
])
def test_avatar_template_rejects_untrusted_or_unsafe_formats(avatar):
    with pytest.raises(PresentationError):
        _profile(chat={"mode": "webhook", "webhook_url_env": "TEST_WEBHOOK", "avatar_url": avatar})
