"""tests/test_dmcc_rich_text.py

Modification():

- DMCC safe rich-text presentation preserves common Discord Markdown in Minecraft.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from bot.mod.dmcc.services.rich_text import parse_discord_markdown, colorize_author_prefix
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


def test_discord_spoiler_is_obfuscated_not_exposed_as_raw_markup():
    segments = parse_discord_markdown("Welcome ||secret|| user")
    assert "".join(str(s["text"]) for s in segments) == "Welcome secret user"
    assert any(s["text"] == "secret" and s["obfuscated"] for s in segments)


def test_code_backticks_do_not_parse_nested_bold_tokens():
    segments = parse_discord_markdown("before `**literal**` after")
    code = [s for s in segments if s["color"] == "gray"]
    assert code and any("**literal**" in s["text"] for s in code)
    assert not any(s["bold"] for s in code)


def test_relay_minecraft_rich_chat_colors_only_discord_author(tmp_path: Path):
    class Gateway:
        def __init__(self):
            self.segments = []

        async def send_minecraft_segments(self, server_id, segments):
            self.segments.append((server_id, segments))

    async def run():
        state = JsonStateRepository(tmp_path / "state.json")
        state.initialize()
        state.set_channel_mapping("survival", "123456789012345678")
        gateway = Gateway()
        relay = DiscordRelayService(state, gateway, rich_chat=True)
        assert await relay.forward_message(
            "color-1", "123456789012345678", "Alex", "Hello **Steve**",
            author_color="#12AB34",
        )
        segments = gateway.segments[0][1]
        assert "".join(str(part["text"]) for part in segments) == "<Alex> Hello Steve"
        assert any(part["text"] == "<Alex> " and part["color"] == "#12AB34" for part in segments)
        assert any("Hello " in part["text"] and part["color"] == "white" for part in segments)
        assert any(part["text"] == "Steve" and part["bold"] for part in segments)
    asyncio.run(run())


def test_colorize_author_prefix_rejects_spoofed_or_invalid_colors():
    plain = parse_discord_markdown("<Alex> hello")
    assert colorize_author_prefix(plain, "<Alex> ", "#CC11ff")[0]["color"] == "#CC11FF"
    assert colorize_author_prefix(plain, "<Alex> ", "#GGGGGG") == plain
    assert colorize_author_prefix(plain, "<Bob> ", "#CC11FF") == plain


def test_fenced_ansi_code_preserves_safe_colors_and_neighbor_text():
    text = "Before ```ansi\n\x1b[31mRed\x1b[0m Plain``` After"
    parts = parse_discord_markdown(text)
    joined = "".join(str(item["text"]) for item in parts)
    assert joined == "Before Red Plain After"
    assert "\x1b" not in joined
    assert any(item["text"] == "Red" and item["color"] == "#AA0000" for item in parts)
    assert any("Plain" in str(item["text"]) and item["color"] == "gray" for item in parts)


def test_ansi_code_rejects_unknown_control_codes_and_stays_bounded():
    text = "```ansi\n\x1b[999m" + "X" * 6000 + "```"
    parts = parse_discord_markdown(text)
    assert parts
    assert len(parts) <= 128
    assert sum(len(str(p["text"]).encode("utf-16-le")) // 2 for p in parts) <= 1800
    assert "\x1b" not in "".join(str(p["text"]) for p in parts)
