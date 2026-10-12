"""tests/test_backup_regressions.py

Modification():

- Covers persistence, tar safety, and tmux launch regressions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bot.mod.mc_backup.domain.errors import BackupOperationError
from bot.mod.mc_backup.domain.models import ManagedBackupServer
from bot.mod.mc_backup.application.schedules import BackupScheduleService
from bot.mod.mc_backup.commands.owner import McBackupOwnerCog
from bot.mod.mc_backup.providers.local_tar import LocalTarBackupProvider
from bot.mod.mc_backup.repositories.json_file import AtomicJsonFile
from bot.mod.mc_backup.repositories.schedules import JsonScheduleRepository


def _server(server_dir: Path, backup_dir: Path) -> ManagedBackupServer:
    return ManagedBackupServer("survival", server_dir, backup_dir, "minecraft", ("java", "-jar", "server.jar"), 3)


def test_atomic_json_quarantines_corrupt_document(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    assert AtomicJsonFile(path).read(lambda: {"ok": True}, lambda value: value) == {"ok": True}
    assert (tmp_path / "state.json.corrupt").is_file()


def test_long_backup_name_and_symlink_are_handled_safely(tmp_path: Path) -> None:
    server_dir, backup_dir = tmp_path / "server", tmp_path / "backups"
    server_dir.mkdir()
    backup_dir.mkdir()
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


def test_schedule_failure_updates_health_and_is_logged(tmp_path: Path, caplog) -> None:
    class Coordinator:
        async def create(self, _server) -> None:
            raise OSError("disk full")

    server = _server(tmp_path / "server", tmp_path / "backups")
    service = BackupScheduleService(
        {server.server_id: server},
        Coordinator(),
        JsonScheduleRepository(tmp_path / "schedules.json"),
    )

    asyncio.run(service.run_due([server.server_id]))

    health = service.health(server.server_id)
    assert health.consecutive_failures == 1
    assert health.last_success_at is None
    assert health.last_failure_at is not None
    assert health.last_error == "OSError: disk full"
    assert "Scheduled backup failed" in caplog.text


def test_owner_status_reports_schedule_failure(tmp_path: Path) -> None:
    class Coordinator:
        async def create(self, _server) -> None:
            raise OSError("disk full")

        async def is_running(self, _server) -> bool:
            return True

    class Context:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send(self, message: str) -> None:
            self.messages.append(message)

    async def run() -> None:
        server = _server(tmp_path / "server", tmp_path / "backups")
        coordinator = Coordinator()
        schedules = BackupScheduleService(
            {server.server_id: server},
            coordinator,
            JsonScheduleRepository(tmp_path / "schedules.json"),
        )
        await schedules.run_due([server.server_id])
        cog = McBackupOwnerCog(
            object(),
            settings=type("Settings", (), {"servers": (server,)})(),
            coordinator=coordinator,
            schedules=schedules,
            confirmation_timeout_seconds=1,
        )
        ctx = Context()

        await McBackupOwnerCog.status.callback(cog, ctx)

        assert "schedule_failures=1" in ctx.messages[0]
        assert "OSError: disk full" in ctx.messages[0]

    asyncio.run(run())
