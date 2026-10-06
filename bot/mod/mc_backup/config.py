"""bot/mod/mc_backup/config.py

Validated settings for the standalone mc_backup feature module.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain.errors import BackupConfigurationError
from .domain.models import ManagedBackupServer


SETTINGS_NAME = "mc_backup"
DEFAULT_SETTINGS: dict[str, object] = {
    "servers": [],
    "history_limit": 200,
    "control_timeout_seconds": 30,
    "confirmation_timeout_seconds": 60,
}


def build_settings_schema(setting_rule):
    """Build Core settings rules lazily to keep this package independently importable."""

    return {
        "servers": setting_rule(list),
        "history_limit": setting_rule(int, minimum=1, maximum=10_000),
        "control_timeout_seconds": setting_rule(int, minimum=1, maximum=600),
        "confirmation_timeout_seconds": setting_rule(int, minimum=5, maximum=600),
    }


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BackupConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _absolute_path(raw: Mapping[str, Any], key: str) -> Path:
    text = _required_text(raw, key)
    path = Path(text)
    if not path.is_absolute():
        raise BackupConfigurationError(f"{key} must be absolute")
    return path.resolve(strict=False)


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class McBackupSettings:
    servers: tuple[ManagedBackupServer, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "McBackupSettings":
        raw_servers = raw.get("servers")
        if not isinstance(raw_servers, Sequence) or isinstance(raw_servers, (str, bytes)):
            raise BackupConfigurationError("servers must be a list")
        servers: list[ManagedBackupServer] = []
        seen_server_ids: set[str] = set()
        seen_sessions: set[str] = set()
        for item in raw_servers:
            if not isinstance(item, Mapping):
                raise BackupConfigurationError("server entry must be an object")
            server_id = _required_text(item, "server_id")
            tmux_session = _required_text(item, "tmux_session")
            if server_id in seen_server_ids:
                raise BackupConfigurationError(f"duplicate server_id: {server_id}")
            if tmux_session in seen_sessions:
                raise BackupConfigurationError(f"duplicate tmux_session: {tmux_session}")
            server_dir = _absolute_path(item, "server_dir")
            backup_dir = _absolute_path(item, "backup_dir")
            if not server_dir.is_dir():
                raise BackupConfigurationError("server_dir must be an existing directory")
            if not backup_dir.is_dir():
                raise BackupConfigurationError("backup_dir must be an existing directory")
            if _is_within(backup_dir, server_dir):
                raise BackupConfigurationError("backup_dir must be outside server_dir")
            start_argv = item.get("start_argv")
            if (
                not isinstance(start_argv, Sequence)
                or isinstance(start_argv, (str, bytes))
                or not start_argv
                or not all(isinstance(argument, str) and argument for argument in start_argv)
            ):
                raise BackupConfigurationError("start_argv must be a non-empty string array")
            keep_automatic = item.get("keep_automatic", 7)
            if not isinstance(keep_automatic, int) or isinstance(keep_automatic, bool) or keep_automatic < 0:
                raise BackupConfigurationError("keep_automatic must be a non-negative integer")
            servers.append(
                ManagedBackupServer(
                    server_id=server_id,
                    server_dir=server_dir,
                    backup_dir=backup_dir,
                    tmux_session=tmux_session,
                    start_argv=tuple(start_argv),
                    keep_automatic=keep_automatic,
                )
            )
            seen_server_ids.add(server_id)
            seen_sessions.add(tmux_session)
        return cls(servers=tuple(servers))

    def require_server(self, server_id: str) -> ManagedBackupServer:
        for server in self.servers:
            if server.server_id == server_id:
                return server
        raise BackupConfigurationError(f"unknown server_id: {server_id}")
