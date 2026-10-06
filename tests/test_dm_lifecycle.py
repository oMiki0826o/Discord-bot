"""
tests/test_dm_lifecycle.py

Modification():

- Release-contract tests for the independent DM Feature Module.
- 維護 test dm lifecycle 的發布版行為與驗證契約。
"""

from __future__ import annotations

from bot.mod.dm import extension
from bot.mod.dm.config import DEFAULT_SETTINGS, DMSettings, build_settings_schema


def test_dm_module_has_no_feature_dependencies_and_valid_settings_contract() -> None:
    assert extension.MODULE_DEPENDENCIES == ()
    assert extension.MODULE_VERSION
    settings = DMSettings.from_mapping(DEFAULT_SETTINGS)
    schema = build_settings_schema(type("Rule", (), {"__init__": lambda self, *args, **kwargs: None}))

    assert settings.recent_senders_limit > 0
    assert settings.forward_map_limit > 0
    assert set(schema) == {"recent_senders_limit", "forward_map_limit", "owner_reply_prefix"}
