"""bot/mod/mc_backup/domain/models.py

Immutable data exchanged between mc_backup layers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ManagedBackupServer:
    server_id: str
    server_dir: Path
    backup_dir: Path
    tmux_session: str
    start_argv: tuple[str, ...]
    keep_automatic: int


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    artifact_id: str
    server_id: str
    created_at: datetime
    automatic: bool
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    server_id: str
    kind: str
    success: bool
    started_at: datetime
    finished_at: datetime
    detail: str


@dataclass(frozen=True, slots=True)
class BackupSchedule:
    server_id: str
    enabled: bool
    time_of_day: str
    timezone: str
