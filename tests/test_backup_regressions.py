"""tests/test_backup_regressions.py

Modification():

- Covers persistence, tar safety, and tmux launch regressions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.mod.mc_backup.domain.errors import BackupOperationError
from bot.mod.mc_backup.domain.models import ManagedBackupServer
from bot.mod.mc_backup.providers.local_tar import LocalTarBackupProvider
from bot.mod.mc_backup.repositories.json_file import AtomicJsonFile


def _server(server_dir: Path, backup_dir: Path) -> ManagedBackupServer:
    return ManagedBackupServer("survival", server_dir, backup_dir, "minecraft", ("java", "-jar", "server.jar"), 3)


def test_atomic_json_quarantines_corrupt_document(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    assert AtomicJsonFile(path).read(lambda: {"ok": True}, lambda value: value) == {"ok": True}
    assert (tmp_path / "state.json.corrupt").is_file()


def test_long_backup_name_and_symlink_are_handled_safely(tmp_path: Path) -> None:
    server_dir, backup_dir = tmp_path / "server", tmp_path / "backups"
    server_dir.mkdir(); backup_dir.mkdir()
    (server_dir / "level.dat").write_bytes(b"world")
    provider = LocalTarBackupProvider()
    artifact = provider._create_sync(_server(server_dir, backup_dir), "a" * 80)
    assert provider._validate_sync(_server(server_dir, backup_dir), artifact.artifact_id) == artifact
    (server_dir / "unsafe-link").symlink_to(tmp_path / "outside")
    with pytest.raises(BackupOperationError, match="unsafe archive member"):
        provider._create_sync(_server(server_dir, backup_dir), "manual")


def test_manifest_rejects_string_automatic_flag() -> None:
    payload = {"artifact_id": "manual-20261006T000000000000Z-deadbeef", "server_id": "survival", "created_at": "2026-10-06T00:00:00+00:00", "automatic": "false", "size_bytes": 1, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="boolean"):
        LocalTarBackupProvider._artifact_from_payload(payload)
