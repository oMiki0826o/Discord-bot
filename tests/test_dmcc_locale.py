"""tests/test_dmcc_locale.py

Modification():

- Validate bilingual Minecraft event templates without runtime HTTP fetching.
"""

from __future__ import annotations

import pytest

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.presentation import PresentationError, PresentationSettings, render_message


def _server(options):
    config = PresentationSettings.from_mapping({"servers": {"survival": options}})
    return config.servers["survival"]


def test_english_templates_render_discord_events_without_changing_default():
    event = MinecraftEvent("player_join", "survival", {"player_name": "Steve"})
    english = render_message(event, _server({"label": "Survival", "locale": "en_US"}), "123")
    traditional = render_message(event, _server({"label": "生存服"}), "123")
    assert english is not None and english.content == "**Steve joined Survival**"
    assert traditional is not None and "加入了" in traditional.content


def test_custom_event_template_overrides_locale():
    profile = _server({
        "locale": "en_US",
        "templates": {"player_join": "Welcome {player} to {server}"},
    })
    event = MinecraftEvent("player_join", "survival", {"player_name": "Steve"})
    assert render_message(event, profile, "123").content == "Welcome Steve to survival"


def test_unrecognized_locale_is_rejected():
    with pytest.raises(PresentationError):
        _server({"locale": "fr_FR"})
