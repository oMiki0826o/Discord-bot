"""tests/test_dmcc_mentions.py

Modification():

- Tests for opt-in targeted Minecraft notifications of Discord user mentions.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bot.mod.dmcc.repositories.links import JsonLinkRepository
from bot.mod.dmcc.repositories.state import JsonStateRepository
from bot.mod.dmcc.services.mentions import MentionConfig, MinecraftMentionService


def test_opt_in_validates_types_and_rate_limits():
    assert not MentionConfig.from_mapping({}).enabled
    assert MentionConfig.from_mapping({"enabled": True}).enabled
    for invalid in ({"enabled": "yes"}, {"enabled": True, "max_targets": 0},
                    {"enabled": True, "max_targets": 200}, {"cooldown_seconds": -1},
                    {"enabled": True, "style": "command"}):
        with pytest.raises(ValueError):
            MentionConfig.from_mapping(invalid)


def test_linked_user_mention_is_targeted_and_cooldown_scoped(tmp_path: Path):
    class Sender:
        def __init__(self):
            self.messages = []
        async def send_packet(self, server, kind, request_id, data):
            self.messages.append((server, kind, request_id, data))

    async def scenario():
        state = JsonStateRepository(tmp_path / "state.json")
        state.initialize()
        state.set_channel_mapping("survival", "123456789012345678")
        links = JsonLinkRepository(tmp_path / "links.json")
        uuid = "123e4567-e89b-12d3-a456-426614174000"
        links.link("234567890123456789", uuid, "Steve")
        clock = [0.]
        sender = Sender()
        service = MinecraftMentionService(
            MentionConfig.from_mapping({"enabled": True}), state, links, sender,
            clock=lambda: clock[0],
        )
        delivered = await service.notify(
            "123456789012345678", "Alex", "Hello @Steve",
            ("234567890123456789", "999999999999999999"),
        )
        assert delivered
        assert len(sender.messages) == 1
        server, kind, req, data = sender.messages[0]
        assert server == "survival"
        assert kind == "player_mention" and req is None
        assert data["player_uuids"] == [uuid]
        assert "Alex" in data["message"]
        assert not await service.notify(
            "123456789012345678", "Alex", "ping", ("234567890123456789",)
        )
        clock[0] += 16
        assert await service.notify(
            "123456789012345678", "Alex", "ping", ("234567890123456789",)
        )
        assert len(sender.messages) == 2

    asyncio.run(scenario())


def test_missing_mapping_prevents_mentions(tmp_path: Path):
    async def scenario():
        state = JsonStateRepository(tmp_path / "state.json")
        state.initialize()
        links = JsonLinkRepository(tmp_path / "links.json")
        class Sender:
            async def send_packet(self, server, kind, req, data):
                raise AssertionError("Must not notify an unmapped server")
        service = MinecraftMentionService(
            MentionConfig.from_mapping({"enabled": True}), state, links, Sender(),
        )
        assert not await service.notify("123456789012345678", "Alex", "hello", ("111111111111111111",))
    asyncio.run(scenario())


def test_title_mentions_and_optional_sound_are_supported():
    config = MentionConfig.from_mapping({"enabled": True, "style": "title", "sound": False})
    assert config.style == "title"
    assert config.sound is False
    assert MentionConfig.from_mapping({"enabled": True}).sound is True
    with pytest.raises(ValueError):
        MentionConfig.from_mapping({"enabled": True, "sound": "off"})


def test_role_mentions_only_accept_complete_guild_snapshots():
    from types import SimpleNamespace
    from bot.mod.dmcc.services.mentions import collect_role_mention_users

    target = SimpleNamespace(id=111111111111111111)
    members = [
        SimpleNamespace(id=222222222222222222, bot=False, roles=[target]),
        SimpleNamespace(id=333333333333333333, bot=False, roles=[target]),
        SimpleNamespace(id=444444444444444444, bot=True, roles=[target]),
    ]
    guild = SimpleNamespace(chunked=True, members=members)
    assert collect_role_mention_users(guild, [target], max_targets=8) == (
        "222222222222222222", "333333333333333333",
    )
    assert collect_role_mention_users(SimpleNamespace(chunked=False, members=members), [target], max_targets=8) == ()
    assert collect_role_mention_users(guild, [target], max_targets=1) == ()
    assert collect_role_mention_users(guild, [target, target], max_targets=8) == (
        "222222222222222222", "333333333333333333",
    )


def test_role_mentions_opt_in_default_off_and_strict_type_check():
    assert MentionConfig.from_mapping({}).role_mentions is False
    assert MentionConfig.from_mapping({"role_mentions": True}).role_mentions is True
    with pytest.raises(ValueError):
        MentionConfig.from_mapping({"role_mentions": "yes"})
