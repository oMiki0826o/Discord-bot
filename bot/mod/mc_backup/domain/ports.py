"""bot/mod/mc_backup/domain/ports.py

Future provider protocols for the standalone module.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Protocol

from .models import BackupArtifact, ManagedBackupServer


class ServerControlPort(Protocol):
    async def is_running(self, server: ManagedBackupServer) -> bool: ...

    async def start(self, server: ManagedBackupServer) -> None: ...

    async def stop(self, server: ManagedBackupServer) -> None: ...


class ArchivePort(Protocol):
    async def create(
        self, server: ManagedBackupServer, *, name: str | None = None
    ) -> BackupArtifact: ...
