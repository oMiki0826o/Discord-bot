"""
tests/test_agent_privileged_users.py

Modification():
- Verify normalized Discord IDs are only used for explicit read-only status.
"""
from __future__ import annotations

import pytest

from bot.mod.agent.config import AgentSettings, DEFAULT_SETTINGS, build_settings_schema
from bot.mod.agent.policy import normalize_discord_id


@pytest.mark.parametrize("mention", ["<@12345678987654321>", "<@!12345678987654321>", "12345678987654321"])
def test_user_id_parses_without_inheriting_roles(mention: str) -> None:
    assert normalize_discord_id(mention) == 12345678987654321


@pytest.mark.parametrize("bad", ["@everyone", "@here", "<@&12345678987654321>", "<@abc>", "0", "-12", ""])
def test_non_user_mention_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_discord_id(bad)


def test_privileged_list_is_deduped_and_does_not_grant_private_memory() -> None:
    values = dict(DEFAULT_SETTINGS, privileged_users=["<@12345678987654321>", "12345678987654321"])
    settings = AgentSettings.from_mapping(values)
    assert settings.privileged_users == (12345678987654321,)
    assert settings.is_privileged(12345678987654321)
    assert not settings.is_privileged(999)


def test_invalid_privileged_settings_are_rejected() -> None:
    from bot.core.settings.schema import SettingRule
    schema = build_settings_schema(SettingRule)
    with pytest.raises(ValueError):
        schema["privileged_users"].validate("agent.privileged_users", ["<@&123>"])
