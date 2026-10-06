"""
tests/test_settings_migration.py

Modification():

- 提供 test settings migration 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import json

import pytest

from bot.core.settings.manager import SettingsManager
from bot.core.settings.migration import migrate_document


def test_migrate_document_applies_every_version_without_mutating_input() -> None:
    original = {"value": 1}

    migrated, versions = migrate_document(
        "example",
        original,
        target_version=2,
        migrations={
            1: lambda data: {**data, "first": True},
            2: lambda data: {**data, "second": True},
        },
    )

    assert original == {"value": 1}
    assert migrated == {
        "value": 1,
        "first": True,
        "second": True,
        "schema_version": 2,
    }
    assert versions == (1, 2)


def test_migrate_document_rejects_missing_or_future_versions() -> None:
    with pytest.raises(RuntimeError, match="缺少.*v2"):
        migrate_document("example", {}, target_version=2, migrations={1: lambda data: data})

    with pytest.raises(RuntimeError, match="高於"):
        migrate_document("example", {"schema_version": 3}, target_version=2, migrations={})


def test_manager_migrates_with_backup_and_is_idempotent(tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    backup_dir = tmp_path / "backups"
    settings_dir.mkdir()
    path = settings_dir / "example.json"
    path.write_text('{"value": 7}\n', encoding="utf-8")
    manager = SettingsManager(settings_dir, backup_dir=backup_dir)

    loaded = manager.register("example", {"schema_version": 1, "value": 0})

    assert loaded == {"schema_version": 1, "value": 7}
    assert len(list(backup_dir.glob("example.v0.*.json"))) == 1
    manager.reload("example")
    assert len(list(backup_dir.glob("example.v0.*.json"))) == 1


def test_manager_rolls_back_file_and_cache_when_migration_fails(tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    path = settings_dir / "example.json"
    original = '{"schema_version": 1, "value": 7}\n'
    path.write_text(original, encoding="utf-8")
    manager = SettingsManager(settings_dir, backup_dir=tmp_path / "backups")

    def fail(_data):
        raise ValueError("boom")

    with pytest.raises(RuntimeError, match="migration"):
        manager.register(
            "example",
            {"schema_version": 2, "value": 0},
            schema_version=2,
            migrations={2: fail},
        )

    assert path.read_text(encoding="utf-8") == original
    assert manager.get("example.value") == 7


def test_manager_reports_pending_status_without_migrating(tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "example.json").write_text(
        json.dumps({"schema_version": 1, "value": 3}),
        encoding="utf-8",
    )
    manager = SettingsManager(settings_dir, backup_dir=tmp_path / "backups")
    manager._defaults["example"] = {"schema_version": 2, "value": 0}
    manager._schema_versions["example"] = 2
    manager._migrations["example"] = {2: lambda data: data}

    status = manager.migration_status("example")

    assert status.current_version == 1
    assert status.target_version == 2
    assert status.pending_versions == (2,)
