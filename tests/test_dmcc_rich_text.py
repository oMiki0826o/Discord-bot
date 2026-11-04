"""tests/test_dmcc_rich_text.py

Modification():

- DMCC safe rich-text presentation preserves common Discord Markdown in Minecraft.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from bot.mod.dmcc.services.rich_text import parse_discord_markdown
from bot.mod.dmcc.repositories.state import JsonStateRepository
from bot.mod.dmcc.services.discord_relay import DiscordRelayService


def test_parses_strong_emphasis_and_code_without_control_sequences():
    result = parse_discord_markdown("hi **bold** and *italic* with ~~strike~~ and `code`")
    assert "".join(part["text"] for part in result) == "hi bold and italic with strike and code"
    assert any(part["text"] == "bold" and part["bold"] for part in result)
    assert any(part["text"] == "italic" and part["italic"] for part in result)
    assert any(part["text"] == "strike" and part["strikethrough"] for part in result)
    assert any(part["text"] == "code" and part["color"] == "gray" for part in result)


def test_segment_limit_and_unclosed_markup_does_not_lose_text():
    original = "hello **still open and " + "A" * 4000
    segments = parse_discord_markdown(original)
    assert len(segments) <= 128
    assert sum(len(part["text"]) for part in segments) <= 1800
    assert "still open" in "".join(part["text"] for part in segments)


def test_opt_in_gateway_sends_minecraft_components_only_when_enabled(tmp_path: Path):
    class Gateway:
        def __init__(self):
            self.text = []
            self.segments = []
        async def send_minecraft_message(self, server_id, message):
            self.text.append((server_id, message))
        async def send_minecraft_segments(self, server_id, segments):
            self.segments.append((server_id, segments))

    async def run():
        state = JsonStateRepository(tmp_path / "state.json")
        state.initialize()
        state.set_channel_mapping("survival", "123456789012345678")
        gateway = Gateway()
        relay = DiscordRelayService(state, gateway, rich_chat=True)
        assert await relay.forward_message(
            "a", "123456789012345678", "Alex", "Hello **Steve**"
        )
        assert len(gateway.segments) == 1
        assert gateway.segments[0][0] == "survival"
        assert any(part["bold"] for part in gateway.segments[0][1])
        assert gateway.text == []
        plain = DiscordRelayService(state, gateway)
        assert await plain.forward_message("b", "123456789012345678", "Alex", "Hello **Steve**")
        assert len(gateway.text) == 1

    asyncio.run(run())


def test_non_bmp_unicode_is_bounded_by_java_utf16_limit():
    formatted = parse_discord_markdown("😀" * 1200)
    joined = "".join(part["text"] for part in formatted)
    assert joined
    assert len(joined.encode("utf-16-le")) // 2 <= 1800


def test_unpaired_double_delimiter_remains_literal():
    original = "Hello **not closed"
    rendered = "".join(item["text"] for item in parse_discord_markdown(original))
    assert rendered == original
