"""bot/mod/dmcc/domain/ports.py
Runtime-checkable ports implemented outside the DMCC domain layer.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .models import AccountLink, BackupArtifact, OperationRecord, ProcessState


@runtime_checkable
class ServerControlPort(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def status(self, target: str | None = None) -> ProcessState: ...

    async def start(self, target: str | None = None) -> None: ...

    async def stop(self, target: str | None = None) -> None: ...

    async def restart(self, target: str | None = None) -> None: ...

    async def kill(self, target: str | None = None) -> None: ...


@runtime_checkable
class BackupPort(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def list(self, server_id: str) -> tuple[BackupArtifact, ...]: ...

    async def create(self, server_id: str, name: str) -> BackupArtifact: ...

    async def validate(self, server_id: str, artifact_id: str) -> BackupArtifact: ...

    async def restore(self, server_id: str, artifact_id: str) -> None: ...

    async def delete(self, server_id: str, artifact_id: str) -> None: ...


@runtime_checkable
class HistoryPort(Protocol):
    def append(self, record: OperationRecord) -> None: ...

    def recent(self, limit: int = 50) -> tuple[OperationRecord, ...]: ...


@runtime_checkable
class LinkRepositoryPort(Protocol):
    def link(self, link: AccountLink) -> AccountLink: ...

    def unlink(self, discord_user_id: str, minecraft_uuid: str) -> bool: ...

    def links_for_discord(self, discord_user_id: str) -> Sequence[AccountLink]: ...
