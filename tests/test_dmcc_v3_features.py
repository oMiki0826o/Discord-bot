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
