"""tests/test_dmcc_link_limits.py

Modification():

- Enforce opt-in per-Discord-account Minecraft link limits without leaking codes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bot.mod.dmcc.services.linking import LinkingService
from bot.mod.dmcc.repositories.links import JsonLinkRepository


def test_link_limit_rejects_second_distinct_account(tmp_path: Path):
    code = iter(("ABCDEF", "GHIJKL"))
    store = JsonLinkRepository(tmp_path / "links.json")
    linking = LinkingService(link_store=store, code_factory=lambda: next(code), max_accounts=1)
    linking.begin_minecraft_link("uuid-a", "Alex")
    assert linking.confirm_discord_link("ABCDEF", "123") is not None
    linking.begin_minecraft_link("uuid-b", "Steve")
    with pytest.raises(ValueError, match="limit"):
        linking.confirm_discord_link("GHIJKL", "123")
    assert [item.minecraft_name for item in store.links_for_discord("123")] == ["Alex"]


def test_default_configuration_remains_unlimited(tmp_path: Path):
    codes = iter(("ABCDEF", "GHIJKL"))
    store = JsonLinkRepository(tmp_path / "links.json")
    linking = LinkingService(link_store=store, code_factory=lambda: next(codes))
    linking.begin_minecraft_link("uuid-a", "Alex")
    linking.confirm_discord_link("ABCDEF", "123")
    linking.begin_minecraft_link("uuid-b", "Steve")
    assert linking.confirm_discord_link("GHIJKL", "123") is not None


def test_negative_link_limit_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        LinkingService(link_store=JsonLinkRepository(tmp_path / "links.json"), max_accounts=-1)
