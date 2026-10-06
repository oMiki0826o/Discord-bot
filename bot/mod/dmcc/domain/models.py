"""bot/mod/dmcc/domain/models.py
Immutable values shared by DMCC application and provider layers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .capabilities import Capability


class BridgeState(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNSUPPORTED = "unsupported"


class ProcessState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


class OperationState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    STOPPING = "stopping"
    BACKING_UP = "backing_up"
    RESTORING = "restoring"
    FAILED = "failed"


class PowerAction(StrEnum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    KILL = "kill"


@dataclass(frozen=True, slots=True)
class ManagedServer:
    server_id: str
    bridge_enabled: bool = False
    control_provider_id: str | None = None
    control_target: str | None = None
    backup_provider_id: str | None = None
    identity_enabled: bool = False
    allow_kill: bool = False

    @property
    def capabilities(self) -> frozenset[Capability]:
        capabilities: set[Capability] = set()
        if self.bridge_enabled:
            capabilities.add(Capability.BRIDGE)
        if self.control_provider_id is not None:
            capabilities.add(Capability.CONTROL)
            if self.allow_kill:
                capabilities.add(Capability.KILL)
        if self.backup_provider_id is not None:
            capabilities.add(Capability.BACKUP)
        if self.identity_enabled:
            capabilities.add(Capability.IDENTITY)
        return frozenset(capabilities)


@dataclass(frozen=True, slots=True)
class ServerStatus:
    server_id: str
    bridge: BridgeState
    process: ProcessState
    operation: OperationState = OperationState.IDLE
    player_count: int | None = None
    max_players: int | None = None
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class AccountLink:
    discord_user_id: str
    minecraft_uuid: str
    minecraft_name: str


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    artifact_id: str
    server_id: str
    created_at: datetime
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    server_id: str
    action: str
    actor_discord_id: str
    started_at: datetime
    completed_at: datetime | None = None
    result: str = "running"
    safe_error: str | None = None
