"""bot/mod/mc_backup/application/backup.py

Safe sequencing for backup, restore, and deletion.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ..domain.models import BackupArtifact, ManagedBackupServer, OperationRecord
from ..repositories.history import JsonHistoryRepository
from .operations import OperationLockPool


class BackupCoordinator:
    def __init__(self, control: object, archive: object, history: JsonHistoryRepository, locks: OperationLockPool) -> None:
        self._control = control
        self._archive = archive
        self._history = history
        self._locks = locks

    async def create(self, server: ManagedBackupServer, *, name: str | None = None) -> BackupArtifact:
        async with self._locks.for_server(server.server_id):
            return await self._run_with_history("backup", server, lambda: self._create(server, name))

    async def restore(self, server: ManagedBackupServer, artifact_id: str) -> None:
        async with self._locks.for_server(server.server_id):
            return await self._run_with_history("restore", server, lambda: self._restore(server, artifact_id))

    async def delete(self, server: ManagedBackupServer, artifact_id: str) -> None:
        async with self._locks.for_server(server.server_id):
            return await self._run_with_history("delete", server, lambda: self._archive.delete(server, artifact_id))

    async def list(self, server: ManagedBackupServer) -> list[BackupArtifact]:
        return await self._archive.list(server)

    async def is_running(self, server: ManagedBackupServer) -> bool:
        return await self._control.is_running(server)

    async def _create(self, server: ManagedBackupServer, name: str | None) -> BackupArtifact:
        was_running = await self._control.is_running(server)
        if was_running:
            await self._control.stop(server)
        try:
            return await self._archive.create(server, name=name)
        finally:
            if was_running:
                await self._control.start(server)

    async def _restore(self, server: ManagedBackupServer, artifact_id: str) -> None:
        await self._archive.validate(server, artifact_id)
        was_running = await self._control.is_running(server)
        if was_running:
            await self._control.stop(server)
        try:
            await self._archive.restore(server, artifact_id)
        finally:
            if was_running:
                await self._control.start(server)

    async def _run_with_history(self, kind: str, server: ManagedBackupServer, operation: object) -> object:
        started_at = datetime.now(UTC)
        success = False
        detail = "completed"
        try:
            result = await operation()  # type: ignore[operator]
            success = True
            return result
        except Exception as exc:
            detail = str(exc) or type(exc).__name__
            raise
        finally:
            self._history.append(
                OperationRecord(
                    operation_id=uuid.uuid4().hex,
                    server_id=server.server_id,
                    kind=kind,
                    success=success,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    detail=detail,
                )
            )
