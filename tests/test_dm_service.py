"""
tests/test_dm_service.py

Modification():

- Tests for the DM bridge's Discord-independent routing state.
- 維護 test dm service 的發布版行為與驗證契約。
"""

from __future__ import annotations

import pytest

from bot.mod.dm.config import DMSettings
from bot.mod.dm.service import DMBridgeService, parse_reply_target


def test_recent_sender_is_lru_bounded() -> None:
    service = DMBridgeService(DMSettings(recent_senders_limit=2, forward_map_limit=2, owner_reply_prefix="Owner: "))

    service.remember_sender("one")
    service.remember_sender("two")
    service.remember_sender("one")
    service.remember_sender("three")

    assert service.last_sender_id == "three"
    assert service.recent_sender_ids == ("one", "three")


def test_forward_mapping_is_bounded_and_resolvable() -> None:
    service = DMBridgeService(DMSettings(recent_senders_limit=2, forward_map_limit=2, owner_reply_prefix="Owner: "))

    service.remember_forward("forward-one", "one")
    service.remember_forward("forward-two", "two")
    service.remember_forward("forward-three", "three")

    assert service.sender_for_forward("forward-one") is None
    assert service.sender_for_forward("forward-three") == "three"


def test_reply_target_uses_explicit_discord_id_or_recent_sender() -> None:
    assert parse_reply_target("123456789012345678 hello") == ("123456789012345678", "hello")
    assert parse_reply_target("hello") == (None, "hello")


@pytest.mark.parametrize("value", ("", "   ", "123456789012345678   "))
def test_reply_target_rejects_blank_content(value: str) -> None:
    with pytest.raises(ValueError, match="content"):
        parse_reply_target(value)
