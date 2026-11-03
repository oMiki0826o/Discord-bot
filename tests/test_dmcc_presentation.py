"""tests/test_dmcc_presentation.py

Modification():

- Implement and verify Minecraft Bridge presentation and safe Discord routing.

Presentation regression tests: route, security, and backward-compatible relay."""
from __future__ import annotations

import asyncio

import pytest

from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings, SettingsError
from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.minecraft_discord_relay import MinecraftDiscordRelayService
from bot.mod.dmcc.services.presentation import render_message

_WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/test_secret"


def _settings(presentation: dict) -> DmccSettings:
    return DmccSettings.from_mapping(
        {
            **DEFAULT_SETTINGS,
            "servers": [{"server_id": "survival"}],
            "presentation": presentation,
        },
        environ={"MC_WEBHOOK": _WEBHOOK, "MC_EVENTS_WEBHOOK": _WEBHOOK},
    )


def test_default_presentation_remains_legacy() -> None:
    settings = _settings({})
    assert not settings.presentation.servers


def test_webhook_chat_has_player_identity_and_custom_server_label() -> None:
    settings = _settings({"servers": {
        "survival": {
            "label": "生存服",
            "chat": {"mode": "webhook", "webhook_url_env": "MC_WEBHOOK"},
        },
    }})
    profile = settings.presentation.servers["survival"]
    event = MinecraftEvent("player_chat", "survival", {
        "player_name": "tinglove711",
        "minecraft_uuid": "123e4567-e89b-12d3-a456-426614174000",
        "message": "yap",
    })

    payload = render_message(event, profile, "111")

    assert payload is not None
    assert payload.mode == "webhook"
    assert payload.channel_id == "111"
    assert payload.content == "yap"
    assert payload.fallback_content == "[生存服] <tinglove711> yap"
    assert payload.username == "[生存服] tinglove711"
    assert "123e4567-e89b-12d3-a456-426614174000/64" in payload.avatar_url
    assert payload.webhook_url == _WEBHOOK


def test_event_webhook_has_independent_name_channel_and_template() -> None:
    settings = _settings({"servers": {
        "survival": {
            "label": "生存服",
            "event_routes": {"player_quit": {
                "mode": "webhook",
                "webhook_url_env": "MC_EVENTS_WEBHOOK",
                "channel_id": "222",
                "username": "KunlunSMP🌸",
            }},
            "templates": {"player_quit": "{player} 離開了 {server}"},
        },
    }})
    event = MinecraftEvent("player_quit", "survival", {"player_name": "[AFK] TygakIB"})
    payload = render_message(event, settings.presentation.servers["survival"], "111")
    assert payload is not None
    assert payload.channel_id == "222"
    assert payload.content == "[AFK] TygakIB 離開了 生存服"
    assert payload.username == "KunlunSMP🌸"
    assert payload.avatar_url is None


def test_custom_chat_template_applies_for_bot_and_webhook() -> None:
    for mode in ("bot", "webhook"):
        chat = {"mode": mode}
        if mode == "webhook":
            chat["webhook_url_env"] = "MC_WEBHOOK"
        settings = _settings({"servers": {"survival": {
            "label": "Survival",
            "chat": chat,
            "templates": {"player_chat": "{player} 說：{message}"},
        }}})
        event = MinecraftEvent("player_chat", "survival", {
            "player_name": "Steve", "message": "hello",
        })
        payload = render_message(event, settings.presentation.servers["survival"], "111")
        assert payload is not None
        assert payload.content == "Steve 說：hello"


def test_disabled_event_returns_no_payload() -> None:
    settings = _settings({"servers": {"survival": {"disabled_events": ["player_join"]}}})
    event = MinecraftEvent("player_join", "survival", {"player_name": "Steve"})
    assert render_message(event, settings.presentation.servers["survival"], "111") is None


@pytest.mark.parametrize("presentation", [
    {"servers": {"survival": {"chat": {"mode": "webhook"}}}},
    {"servers": {"survival": {"chat": {"mode": "insecure"}}}},
    {"servers": {"unknown": {"label": "unknown"}}},
    {"servers": {"survival": {"templates": {"player_quit": "{player.__class__}"}}}},
    {"servers": {"survival": {"event_channels": {"not_a_real_event": "222"}}}},
    {"servers": {"survival": {
        "events": {"mode": "webhook", "webhook_url_env": "MC_EVENTS_WEBHOOK"},
        "event_channels": {"player_quit": "222"},
    }}},
    {"servers": {"survival": {"templates": {"player_quit": "{player:10000}"}}}},
])
def test_rejects_invalid_presentation(presentation: dict) -> None:
    with pytest.raises(SettingsError):
        _settings(presentation)


def test_rejects_webhook_to_non_discord_host() -> None:
    with pytest.raises(SettingsError):
        DmccSettings.from_mapping(
            {**DEFAULT_SETTINGS, "servers": [{"server_id": "survival"}],
             "presentation": {"servers": {"survival": {
                 "chat": {"mode": "webhook", "webhook_url_env": "EVIL"}
             }}}},
            environ={"EVIL": "https://not-discord.example/api/webhooks/123/token"},
        )


def test_legacy_sender_and_original_format_still_work(tmp_path) -> None:
    from bot.mod.dmcc.repositories.state import JsonStateRepository

    class Sender:
        def __init__(self) -> None:
            self.sent = []

        async def send_discord_message(self, channel_id: str, content: str) -> None:
            self.sent.append((channel_id, content))

    state = JsonStateRepository(tmp_path / "state.json")
    state.initialize()
    state.set_channel_mapping("survival", "111")
    sender = Sender()

    async def check() -> None:
        relay = MinecraftDiscordRelayService(state, sender)
        assert await relay.forward(MinecraftEvent(
            "player_chat", "survival", {"player_name": "Steve", "message": "hello"}
        ))
    asyncio.run(check())
    assert sender.sent == [("111", "<Steve> hello")]


def test_new_sender_uses_presentation_payload(tmp_path) -> None:
    from bot.mod.dmcc.repositories.state import JsonStateRepository

    class Sender:
        def __init__(self) -> None:
            self.payloads = []

        async def send_discord_payload(self, payload) -> None:
            self.payloads.append(payload)

    state = JsonStateRepository(tmp_path / "state.json")
    state.initialize()
    state.set_channel_mapping("survival", "111")
    sender = Sender()
    presentation = _settings({"servers": {"survival": {
        "events": {"mode": "webhook", "webhook_url_env": "MC_EVENTS_WEBHOOK"},
        "templates": {"player_join": "{player} 加入了 {server}"},
    }}}).presentation

    async def check() -> None:
        relay = MinecraftDiscordRelayService(state, sender, presentation)
        assert await relay.forward(MinecraftEvent("player_join", "survival", {
            "player_name": "Steve",
        }))
    asyncio.run(check())
    assert sender.payloads[0].content == "Steve 加入了 survival"
    assert sender.payloads[0].mode == "webhook"
