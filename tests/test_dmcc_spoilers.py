"""tests/test_dmcc_spoilers.py

Modification():

- Require safe hover-reveal spoiler rendering without untrusted click actions.
"""
from __future__ import annotations

from bot.mod.dmcc.services.rich_text import parse_discord_markdown


def test_spoiler_is_bounded_hover_component_and_preserves_adjacent_bold():
    parts = parse_discord_markdown("hello ||hidden **secret**|| **shown**")
    assert "".join(str(part["text"]) for part in parts) == "hello [spoiler] shown"
    spoiler = next(part for part in parts if part.get("text") == "[spoiler]")
    assert spoiler["hover_text"] == "hidden **secret**"
    assert "click_url" not in spoiler
    assert any(part.get("bold") and part.get("text") == "shown" for part in parts)


def test_empty_or_unclosed_spoiler_keeps_plain_text():
    assert "".join(str(p["text"]) for p in parse_discord_markdown("||open")) == "||open"
