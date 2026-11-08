"""tests/test_dmcc_v3_features.py

Modification():

- Validate the preview feature schema, safe rich segment templates and defaults.
"""
from __future__ import annotations

import pytest

from bot.mod.dmcc.services.v3_features import V3FeatureConfig
from bot.mod.dmcc.services.v3_templates import render_segments


def test_v3_feature_schema_is_opt_in_and_private_messages_remain_private():
    default = V3FeatureConfig.from_mapping({})
    assert not default.enabled
    assert not default.allows("discord_to_minecraft", "markdown")
    active = V3FeatureConfig.from_mapping({
        "enabled": True,
        "source_events": {"say": True, "msg": True},
        "message_parsing": {"discord_to_minecraft": {"markdown": True}},
    })
    assert active.allows("discord_to_minecraft", "markdown")
    assert active.allows_source("say")
    assert not active.allows_source("msg")


@pytest.mark.parametrize("invalid", [
    {"enabled": "true"},
    {"message_parsing": {"discord_to_minecraft": {"markdown": "true"}}},
    {"message_parsing": {"private_data": {}}},
    {"templates": {"user_message": [{"text": "{player.__class__}"}]}},
    {"templates": {"user_message": [{"text": "{message}", "color": "run_command"}]}},
    {"templates": {"user_message": [{"text": "{message}", "click_url": "https://site"}]}},
])
def test_v3_rejects_invalid_or_untrusted_settings(invalid):
    with pytest.raises(ValueError):
        V3FeatureConfig.from_mapping(invalid)


def test_rich_template_keeps_message_formatting_and_clip_limits():
    segments = render_segments(
        [{"text": "[{server}] <{effective_name}> ", "bold": True, "color": "{role_color}"},
         {"text": "{message}", "color": "gray"}],
        {"server": "SMP", "effective_name": "Alex", "role_color": "#1234AB"},
        [{"text": "Hi ", "color": "white"},
         {"text": "World", "bold": True, "color": "white"}],
    )
    assert "".join(str(p["text"]) for p in segments) == "[SMP] <Alex> Hi World"
    assert segments[0]["color"] == "#1234AB"
    assert segments[-1]["bold"]
    clipped = render_segments([{"text": "{message}"}], {},
        [{"text": "🦋" * 2000, "color": "white"}])
    assert sum(len(str(p["text"]).encode("utf-16-le")) // 2 for p in clipped) <= 1800



def test_config_wires_v3_feature_matrix_and_requires_opt_in():
    from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings, SettingsError
    defaults = DmccSettings.from_mapping(DEFAULT_SETTINGS)
    assert not defaults.v3_features.enabled
    custom = DmccSettings.from_mapping({
        **DEFAULT_SETTINGS,
        "v3_features": {
            "enabled": True,
            "message_parsing": {"discord_to_minecraft": {"attachments": False}},
            "templates": {"user_message": [
                {"text": "[{server}] "},
                {"text": "{message}", "color": "gray"},
            ]},
        },
    })
    assert custom.v3_features.enabled
    assert not custom.v3_features.allows("discord_to_minecraft", "attachments")
    with pytest.raises(SettingsError):
        DmccSettings.from_mapping({**DEFAULT_SETTINGS, "v3_features": {"enabled": "yes"}})


def test_discord_relay_uses_v3_user_message_template(tmp_path):
    import asyncio
    from bot.mod.dmcc.repositories.state import JsonStateRepository
    from bot.mod.dmcc.services.discord_relay import DiscordRelayService

    class Gateway:
        def __init__(self):
            self.sent = []
        async def send_minecraft_segments(self, server_id, segments):
            self.sent.append((server_id, segments))
    state = JsonStateRepository(tmp_path / "state.json")
    state.initialize()
    state.set_channel_mapping("survival", "123456789012345678")
    features = V3FeatureConfig.from_mapping({
        "enabled": True,
        "templates": {"user_message": [
            {"text": "[{server}] ", "color": "gold"},
            {"text": "<{effective_name}> ", "color": "{role_color}"},
            {"text": "{message}", "color": "gray"},
        ]},
    })
    gateway = Gateway()
    relay = DiscordRelayService(state, gateway, features=features)
    assert asyncio.run(relay.forward_message(
        "121", "123456789012345678", "Alex", "Hello **Steve**", author_color="#AA55CC"
    ))
    segs = gateway.sent[0][1]
    assert "".join(str(s["text"]) for s in segs) == "[survival] <Alex> Hello Steve"
    assert any(p.get("bold") and p.get("text") == "Steve" for p in segs)
