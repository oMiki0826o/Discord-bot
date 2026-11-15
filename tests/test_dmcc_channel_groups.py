"""Shared Discord-channel groups fan out only configured relay kinds."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bot.mod.dmcc.repositories.state import JsonStateRepository
from bot.mod.dmcc.services.discord_relay import DiscordRelayService


class Gateway:
    def __init__(self, offline: set[str] = set()) -> None:
        self.offline = offline
        self.sent: list[tuple[str, str]] = []

    async def send_minecraft_message(self, server_id: str, message: str) -> None:
        if server_id in self.offline:
            raise LookupError(server_id)
        self.sent.append((server_id, message))


def test_shared_group_persists_ordered_members_and_rejects_legacy_collision(tmp_path: Path) -> None:
    state = JsonStateRepository(tmp_path / "state.json")
    state.set_channel_group("100", ("survival", "creative"))
    assert state.channel_group_for_channel("100")["server_ids"] == ["survival", "creative"]
    assert state.channel_for_server("creative") == "100"
    with pytest.raises(ValueError, match="already mapped"):
        state.set_channel_mapping("mirror", "100")


def test_shared_group_can_be_removed_without_touching_other_state(tmp_path: Path) -> None:
    state = JsonStateRepository(tmp_path / "state.json")
    state.set_channel_group("100", ("survival", "creative"))
    state.set_channel_mapping("mirror", "200")
    assert state.remove_channel_group("100") is True
    assert state.channel_group_for_channel("100") is None
    assert state.channel_for_server("mirror") == "200"


def test_server_cannot_belong_to_a_direct_mapping_and_shared_group(tmp_path: Path) -> None:
    state = JsonStateRepository(tmp_path / "state.json")
    state.set_channel_mapping("survival", "200")
    with pytest.raises(ValueError, match="server_id is already mapped"):
        state.set_channel_group("100", ("survival", "creative"))


def test_shared_group_fans_out_messages_but_suppresses_optional_metadata_by_default(tmp_path: Path) -> None:
    async def check() -> None:
        state = JsonStateRepository(tmp_path / "state.json")
        state.set_channel_group("100", ("survival", "creative", "mirror"))
        gateway = Gateway({"mirror"})
        relay = DiscordRelayService(state, gateway)
        assert await relay.forward_message("m1", "100", "Alex", "hello")
        assert gateway.sent == [("survival", "<Alex> hello"), ("creative", "<Alex> hello")]
        assert not await relay.forward_edit("m1", "updated")
        assert not await relay.forward_delete("m1")
        assert not await relay.forward_reaction("m1", "Steve", "👍")
    asyncio.run(check())


def test_shared_group_defaults_relay_safe_media_but_not_discord_ui(tmp_path: Path) -> None:
    async def check() -> None:
        state = JsonStateRepository(tmp_path / "state.json")
        state.set_channel_group("100", ("survival", "creative", "mirror"))
        gateway = Gateway()
        relay = DiscordRelayService(state, gateway)
        assert await relay.forward_message(
            "m1", "100", "Alex", "hello <:flower:123456789012345678>",
            reply_preview="previous message",
            attachment_urls=("https://cdn.example/path/screen.png",),
            sticker_names=("Flower",),
            embed_summaries=(("server status", "https://example.invalid/status"),),
            poll_summary=("Which mode?", ("survival", "creative")),
            component_summaries=("Refresh",),
        )
        assert [server for server, _ in gateway.sent] == ["survival", "creative", "mirror"]
        payload = gateway.sent[0][1]
        assert "↪ previous message" in payload
        assert "<Alex> hello :flower:" in payload
        assert "<image> screen.png — https://cdn.example/path/screen.png" in payload
        assert "Sticker: Flower" in payload
        assert "server status" not in payload
        assert "Which mode?" not in payload
        assert "Refresh" not in payload
    asyncio.run(check())


def test_shared_group_can_opt_into_edit_delete_reaction_and_reply(tmp_path: Path) -> None:
    async def check() -> None:
        state = JsonStateRepository(tmp_path / "state.json")
        state.set_channel_group("100", ("survival", "creative"), edits=True, deletes=True, reactions=True, replies=True)
        gateway = Gateway()
        relay = DiscordRelayService(state, gateway)
        assert await relay.forward_message("m1", "100", "Alex", "hello", reply_preview="previous")
        assert await relay.forward_edit("m1", "updated")
        assert await relay.forward_reaction("m1", "Steve", "👍")
        assert await relay.forward_delete("m1")
        assert [server for server, _ in gateway.sent] == ["survival", "creative"] * 4
    asyncio.run(check())
