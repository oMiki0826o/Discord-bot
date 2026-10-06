"""bot/mod/dmcc/config.py
Validated DMCC settings and environment-backed secret resolution.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from .domain.models import ManagedServer


SETTINGS_NAME = "dmcc"

DEFAULT_SETTINGS: dict[str, object] = {
    "gateway": {"host": "127.0.0.1", "port": 8765},
    "frame_max_bytes": 262_144,
    "heartbeat_interval_seconds": 15.0,
    "heartbeat_timeout_seconds": 45.0,
    "request_timeout_seconds": 15.0,
    "mode": "standalone",
    "cross_server_relay": False,
    "providers": {"control": [], "backup": []},
    "servers": [],
    "permissions": {"user_mappings": [], "role_mappings": []},
}


def build_settings_schema(rule_type):
    """Return the Core Settings schema without importing Core at module import."""

    return {
        "gateway": rule_type(dict),
        "frame_max_bytes": rule_type(int, minimum=1, maximum=1_048_576),
        "heartbeat_interval_seconds": rule_type((int, float), minimum=0.01, maximum=3_600),
        "heartbeat_timeout_seconds": rule_type((int, float), minimum=0.02, maximum=7_200),
        "request_timeout_seconds": rule_type((int, float), minimum=0.01, maximum=600),
        "mode": rule_type(str),
        "cross_server_relay": rule_type(bool),
        "providers": rule_type(dict),
        "servers": rule_type(list),
        "permissions": rule_type(dict),
    }


class SettingsError(ValueError):
    """DMCC settings violate a type, identity, or safety constraint."""


@dataclass(frozen=True, slots=True)
class ControlProviderDefinition:
    provider_id: str
    provider_type: str
    options: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BackupProviderDefinition:
    provider_id: str
    provider_type: str
    options: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DmccSettings:
    host: str
    port: int
    frame_max_bytes: int
    heartbeat_interval_seconds: float
    heartbeat_timeout_seconds: float
    request_timeout_seconds: float
    mode: str
    cross_server_relay: bool
    servers: tuple[ManagedServer, ...]
    control_providers: tuple[ControlProviderDefinition, ...] = ()
    backup_providers: tuple[BackupProviderDefinition, ...] = ()
    _bridge_secrets: Mapping[str, str] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, object],
        environ: Mapping[str, str] | None = None,
    ) -> "DmccSettings":
        if not isinstance(raw, Mapping):
            raise SettingsError("dmcc settings must be an object")
        environment = os.environ if environ is None else environ
        gateway = _mapping(raw.get("gateway"), "gateway")
        host, port = _gateway(gateway)
        frame_max_bytes, interval, timeout, request_timeout = _limits(raw)
        mode = raw.get("mode", DEFAULT_SETTINGS["mode"])
        if mode not in {"single_server", "standalone", "multi_server_client"}:
            raise SettingsError("mode must be single_server, standalone, or multi_server_client")
        cross_server_relay = raw.get("cross_server_relay", False)
        if type(cross_server_relay) is not bool:
            raise SettingsError("cross_server_relay must be a boolean")

        providers = _mapping(raw.get("providers", {"control": [], "backup": []}), "providers")
        controls = _control_providers(providers.get("control", []), environment)
        backups = _backup_providers(providers.get("backup", []))
        servers, bridge_secrets = _servers(raw.get("servers"), controls, backups, environment)
        _validate_local_paths(servers, controls, backups)
        return cls(
            host=host,
            port=port,
            frame_max_bytes=frame_max_bytes,
            heartbeat_interval_seconds=interval,
            heartbeat_timeout_seconds=timeout,
            request_timeout_seconds=request_timeout,
            mode=str(mode),
            cross_server_relay=cross_server_relay,
            servers=servers,
            control_providers=controls,
            backup_providers=backups,
            _bridge_secrets=MappingProxyType(bridge_secrets),
        )

    def server_secret(self, server_id: str) -> str | None:
        return self._bridge_secrets.get(server_id)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SettingsError(f"{name} must be an object")
    return value


def _gateway(raw: Mapping[str, object]) -> tuple[str, int]:
    host = raw.get("host")
    port = raw.get("port")
    if host not in {"127.0.0.1", "0.0.0.0"}:
        raise SettingsError("gateway host must be 127.0.0.1 or 0.0.0.0")
    if type(port) is not int or not 0 <= port <= 65535:
        raise SettingsError("gateway port must be between 0 and 65535")
    return str(host), port


def _limits(raw: Mapping[str, object]) -> tuple[int, float, float, float]:
    frame = raw.get("frame_max_bytes", DEFAULT_SETTINGS["frame_max_bytes"])
    interval = raw.get("heartbeat_interval_seconds", DEFAULT_SETTINGS["heartbeat_interval_seconds"])
    timeout = raw.get("heartbeat_timeout_seconds", DEFAULT_SETTINGS["heartbeat_timeout_seconds"])
    request = raw.get("request_timeout_seconds", DEFAULT_SETTINGS["request_timeout_seconds"])
    if type(frame) is not int or not 1 <= frame <= 1_048_576:
        raise SettingsError("frame_max_bytes must be between 1 and 1048576")
    if type(interval) not in {int, float} or float(interval) <= 0:
        raise SettingsError("heartbeat_interval_seconds must be positive")
    if type(timeout) not in {int, float} or float(timeout) <= float(interval):
        raise SettingsError("heartbeat_timeout_seconds must exceed interval")
    if type(request) not in {int, float} or float(request) <= 0:
        raise SettingsError("request_timeout_seconds must be positive")
    return frame, float(interval), float(timeout), float(request)


def _provider_list(value: object, kind: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise SettingsError(f"{kind} providers must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise SettingsError(f"{kind} provider must be an object")
    return list(value)


def _control_providers(
    value: object,
    environ: Mapping[str, str],
) -> tuple[ControlProviderDefinition, ...]:
    definitions: list[ControlProviderDefinition] = []
    seen: set[str] = set()
    for raw in _provider_list(value, "control"):
        provider_id, provider_type, options = _provider_header(raw, "control", seen)
        if provider_type not in {"local_tmux", "pterodactyl", "mcsm"}:
            raise SettingsError(f"unsupported control provider type: {provider_type}")
        if provider_type == "local_tmux":
            _require_absolute_path(options.get("server_dir"), "server_dir")
            _require_text(options.get("session_name"), "session_name")
            argv = options.get("start_argv")
            if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
                raise SettingsError("start_argv must be a non-empty string list")
        else:
            _require_text(options.get("base_url"), "base_url")
            secret_name = _require_text(options.get("api_key_env"), "api_key_env")
            _require_environment(secret_name, environ)
        definitions.append(ControlProviderDefinition(provider_id, provider_type, options))
    return tuple(definitions)


def _backup_providers(value: object) -> tuple[BackupProviderDefinition, ...]:
    definitions: list[BackupProviderDefinition] = []
    seen: set[str] = set()
    for raw in _provider_list(value, "backup"):
        provider_id, provider_type, options = _provider_header(raw, "backup", seen)
        if provider_type != "local_tar":
            raise SettingsError(f"unsupported backup provider type: {provider_type}")
        _require_absolute_path(options.get("backup_dir"), "backup_dir")
        definitions.append(BackupProviderDefinition(provider_id, provider_type, options))
    return tuple(definitions)


def _provider_header(
    raw: Mapping[str, object],
    kind: str,
    seen: set[str],
) -> tuple[str, str, Mapping[str, object]]:
    provider_id = _require_text(raw.get("provider_id"), "provider_id")
    if provider_id in seen:
        raise SettingsError(f"duplicate {kind} provider_id: {provider_id}")
    seen.add(provider_id)
    provider_type = _require_text(raw.get("type"), "type")
    options = MappingProxyType(dict(_mapping(raw.get("options"), "options")))
    return provider_id, provider_type, options


def _servers(
    value: object,
    controls: tuple[ControlProviderDefinition, ...],
    backups: tuple[BackupProviderDefinition, ...],
    environ: Mapping[str, str],
) -> tuple[tuple[ManagedServer, ...], dict[str, str]]:
    if not isinstance(value, list):
        raise SettingsError("servers must be a list")
    control_ids = {item.provider_id for item in controls}
    backup_ids = {item.provider_id for item in backups}
    servers: list[ManagedServer] = []
    secrets: dict[str, str] = {}
    seen: set[str] = set()
    for raw_value in value:
        raw = _mapping(raw_value, "server")
        server_id = _require_text(raw.get("server_id"), "server_id")
        if server_id in seen:
            raise SettingsError(f"duplicate server_id: {server_id}")
        seen.add(server_id)
        if "secret" in raw:
            raise SettingsError("servers[].secret is not supported; use bridge.secret_env")
        bridge = _mapping(raw.get("bridge", {"enabled": False}), "bridge")
        bridge_enabled = bridge.get("enabled", False)
        if type(bridge_enabled) is not bool:
            raise SettingsError("bridge.enabled must be a boolean")
        if bridge_enabled:
            secret_name = _require_text(bridge.get("secret_env"), "bridge.secret_env")
            secrets[server_id] = _require_environment(secret_name, environ)
        control_id = _optional_text(raw.get("control_provider"), "control_provider")
        backup_id = _optional_text(raw.get("backup_provider"), "backup_provider")
        if control_id is not None and control_id not in control_ids:
            raise SettingsError(f"unknown control provider: {control_id}")
        if backup_id is not None and backup_id not in backup_ids:
            raise SettingsError(f"unknown backup provider: {backup_id}")
        servers.append(
            ManagedServer(
                server_id=server_id,
                bridge_enabled=bridge_enabled,
                control_provider_id=control_id,
                control_target=_optional_text(raw.get("control_target"), "control_target"),
                backup_provider_id=backup_id,
                identity_enabled=bool(raw.get("identity_enabled", True)),
                allow_kill=bool(raw.get("allow_kill", False)),
            )
        )
    return tuple(servers), secrets


def _validate_local_paths(
    servers: tuple[ManagedServer, ...],
    controls: tuple[ControlProviderDefinition, ...],
    backups: tuple[BackupProviderDefinition, ...],
) -> None:
    control_by_id = {item.provider_id: item for item in controls}
    backup_by_id = {item.provider_id: item for item in backups}
    for server in servers:
        control = control_by_id.get(server.control_provider_id)
        backup = backup_by_id.get(server.backup_provider_id)
        if control is None or backup is None:
            continue
        if control.provider_type != "local_tmux" or backup.provider_type != "local_tar":
            continue
        server_dir = Path(str(control.options["server_dir"])).resolve(strict=False)
        backup_dir = Path(str(backup.options["backup_dir"])).resolve(strict=False)
        if backup_dir == server_dir or server_dir in backup_dir.parents:
            raise SettingsError("backup_dir must not be inside server_dir")


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SettingsError(f"{name} must be a non-empty string")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name)


def _require_absolute_path(value: object, name: str) -> Path:
    path = Path(_require_text(value, name))
    if not path.is_absolute():
        raise SettingsError(f"{name} must be an absolute path")
    return path


def _require_environment(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name)
    if not value:
        raise SettingsError(f"missing required environment variable: {name}")
    return value
