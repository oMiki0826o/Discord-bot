"""tests/test_dmcc_rich_messages.py

Modification():

- Verify bounded and safe DMCC v3-style Discord message metadata handling.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from bot.mod.dmcc.services.message_format import format_discord_content, render_extras
from bot.mod.dmcc.services.discord_relay import DiscordRelayService
from bot.mod.dmcc.repositories.state import JsonStateRepository


def test_custom_emoji_mentions_and_timestamps_resolve_without_discord_markup() -> None:
    result = format_discord_content(
        "Hello <@123456789012345678> <:flower:123456789012345678> <#987654321098765432> <t:0:R>",
        mentions={
            "123456789012345678": "Steve",
            "987654321098765432": "general",
        },
    )
    assert "@Steve" in result
    assert ":flower:" in result
    assert "#general" in result
    assert "1970" in result
    assert "<@" not in result and "<:" not in result


def test_unknown_mentions_not_exposed_as_raw_discord_markup() -> None:
    content = "<@123456789012345678> <@&123456789012345678> <#123456789012345678> @everyone @here"
    result = format_discord_content(content)
    assert "<@" not in result and "<#" not in result
    assert "@everyone" not in result and "@here" not in result


def test_discord_rich_metadata_is_truncated_and_bounded() -> None:
    extras = render_extras(
        attachments=[("screen.png", "https://cdn.discordapp.com/attachments/1/2/screen.png") for _ in range(10)],
        stickers=["Hi" for _ in range(8)],
        embeds=[("Hello", "https://example.org") for _ in range(8)],
        poll=("Best option?", ["A", "B", "C"]),
    )
    assert extras.count("Attachment:") == 5
    assert extras.count("Sticker:") == 3
    assert extras.count("Embed:") == 3
    assert "Poll: Best option?" in extras
    assert len(extras) < 1800


def test_relay_preserves_legacy_text_and_forwards_reaction_only_for_known_message(tmp_path: Path) -> None:
    class Sender:
        def __init__(self):
            self.sent: list[str] = []

        async def send_minecraft_message(self, server_id, message):
            self.sent.append(message)

    async def scenario() -> None:
        sender = Sender()
        state = JsonStateRepository(tmp_path / "state.json")
        state.initialize()
        state.set_channel_mapping("survival", "123456789012345678")
        relay = DiscordRelayService(state, sender)
        assert await relay.forward_message(
            "112", "123456789012345678", "Alex", "nice <:spark:123456789012345678>",
            sticker_names=("Wave",), embed_summaries=(("Guide", "https://example.org"),),
            poll_summary=("Question?", ("Yes", "No")),
        )
        assert ":spark:" in sender.sent[0]
        assert "Sticker: Wave" in sender.sent[0]
        assert "Poll: Question?" in sender.sent[0]
        assert await relay.forward_reaction("112", "Steve", "👍")
        assert "Steve" in sender.sent[-1] and "👍" in sender.sent[-1]
        assert not await relay.forward_reaction("unknown", "Steve", "👍")
        assert len(sender.sent) == 2

    asyncio.run(scenario())


def test_relay_rich_payload_handles_only_mapped_channel(tmp_path: Path) -> None:
    class Sender:
        async def send_minecraft_message(self, server_id, message):
            raise AssertionError("Should not forward")

    async def scenario() -> None:
        state = JsonStateRepository(tmp_path / "state.json")
        state.initialize()
        relay = DiscordRelayService(state, Sender())
        assert not await relay.forward_message("113", "111111111111111111", "Steve", "Test")
        assert not await relay.forward_reaction("113", "Alex", "thumbs")

    asyncio.run(scenario())
