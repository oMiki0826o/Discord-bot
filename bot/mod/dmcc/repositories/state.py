"""bot/mod/dmcc/repositories/state.py
Persistent Discord channel mappings for configured Minecraft servers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from pathlib import Path

from .json_file import AtomicJsonFile


_GROUP_DEFAULTS = {
    "replies": True, "attachments": True, "stickers": True,
    "custom_emojis": True, "embeds": False, "polls": False,
    "components": False, "edits": False, "deletes": False, "reactions": False,
}


def _validate(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("DMCC state must be an object")
    mappings = value.get("channel_mappings")
    if not isinstance(mappings, dict) or any(
        not isinstance(server_id, str) or not isinstance(channel_id, str)
        for server_id, channel_id in mappings.items()
    ):
        raise ValueError("channel_mappings must contain string IDs")
    groups = value.get("channel_groups", {})
    if not isinstance(groups, dict):
        raise ValueError("channel_groups must be an object")
    assigned_servers = set(mappings)
    for channel_id, group in groups.items():
        if not isinstance(channel_id, str) or not channel_id.strip() or not isinstance(group, dict):
            raise ValueError("channel_groups must contain channel objects")
        server_ids = group.get("server_ids")
        if (
            not isinstance(server_ids, list)
            or not server_ids
            or len(set(server_ids)) != len(server_ids)
            or any(not isinstance(server_id, str) or not server_id.strip() for server_id in server_ids)
        ):
            raise ValueError("channel group server_ids must be a non-empty unique string list")
        if set(group) - {"server_ids", *_GROUP_DEFAULTS}:
            raise ValueError("channel group contains an unknown relay option")
        if any(type(group.get(name, default)) is not bool for name, default in _GROUP_DEFAULTS.items()):
            raise ValueError("channel group relay options must be booleans")
        if channel_id in mappings.values():
            raise ValueError("channel cannot be both a direct mapping and a shared group")
        if assigned_servers.intersection(server_ids):
            raise ValueError("a server can belong to only one channel mapping or group")
        assigned_servers.update(server_ids)
    return value


class JsonStateRepository:
    def __init__(self, path: Path) -> None:
        self._file = AtomicJsonFile(path, _validate)

    def initialize(self) -> None:
        self._file.write(self._read())

    def set_channel_mapping(self, server_id: str, channel_id: str) -> None:
        self._require(server_id, "server_id")
        self._require(channel_id, "channel_id")
        document = self._read()
        if channel_id in self._groups(document):
            raise ValueError("channel_id is already mapped to a shared group")
        if self._server_group_owner(document, server_id) is not None:
            raise ValueError("server_id is already mapped to a shared group")
        mappings = self._mappings(document)
        owner = next((key for key, value in mappings.items() if value == channel_id), None)
        if owner is not None and owner != server_id:
            raise ValueError("channel_id is already mapped to another server")
        mappings[server_id] = channel_id
        self._file.write(document)

    def set_channel_group(self, channel_id: str, server_ids: tuple[str, ...], **options: bool) -> None:
        self._require(channel_id, "channel_id")
        if not server_ids or len(set(server_ids)) != len(server_ids):
            raise ValueError("channel group server IDs must be non-empty and unique")
        if any(not isinstance(value, str) or not value.strip() for value in server_ids):
            raise ValueError("channel group server IDs must be non-empty and unique")
        document = self._read()
        if channel_id in self._mappings(document).values():
            raise ValueError("channel_id is already mapped to another server")
        for server_id in server_ids:
            direct_channel = self._mappings(document).get(server_id)
            group_channel = self._server_group_owner(document, server_id)
            if direct_channel is not None and direct_channel != channel_id:
                raise ValueError("server_id is already mapped to another channel")
            if group_channel is not None and group_channel != channel_id:
                raise ValueError("server_id is already mapped to another shared group")
        valid = set(_GROUP_DEFAULTS)
        if set(options) - valid or any(type(value) is not bool for value in options.values()):
            raise ValueError("invalid channel group relay option")
        self._groups(document)[channel_id] = {"server_ids": list(server_ids), **_GROUP_DEFAULTS, **options}
        self._file.write(document)

    def channel_group_for_channel(self, channel_id: str) -> dict[str, object] | None:
        value = self._groups(self._read()).get(channel_id)
        return dict(value) if isinstance(value, dict) else None

    def remove_channel_group(self, channel_id: str) -> bool:
        self._require(channel_id, "channel_id")
        document = self._read()
        groups = self._groups(document)
        if channel_id not in groups:
            return False
        del groups[channel_id]
        self._file.write(document)
        return True

    def channel_for_server(self, server_id: str) -> str | None:
        document = self._read()
        direct = self._mappings(document).get(server_id)
        if direct is not None:
            return direct
        for channel_id, group in self._groups(document).items():
            if isinstance(group, dict) and server_id in group.get("server_ids", []):
                return channel_id
        return None

    def server_for_channel(self, channel_id: str) -> str | None:
        return next(
            (server_id for server_id, value in self._mappings(self._read()).items() if value == channel_id),
            None,
        )

    def remove_channel_mapping(self, server_id: str) -> bool:
        self._require(server_id, "server_id")
        document = self._read()
        mappings = self._mappings(document)
        if server_id not in mappings:
            return False
        del mappings[server_id]
        self._file.write(document)
        return True

    def channel_mapping_count(self) -> int:
        document = self._read()
        return len(self._mappings(document)) + len(self._groups(document))

    def _read(self) -> dict[str, object]:
        result = self._file.read({"channel_mappings": {}})
        result.setdefault("channel_groups", {})
        return result

    @staticmethod
    def _mappings(document: dict[str, object]) -> dict[str, str]:
        mappings = document["channel_mappings"]
        assert isinstance(mappings, dict)
        return mappings

    @staticmethod
    def _groups(document: dict[str, object]) -> dict[str, object]:
        groups = document["channel_groups"]
        if not isinstance(groups, dict):
            raise ValueError("channel_groups must be an object")
        return groups

    @classmethod
    def _server_group_owner(cls, document: dict[str, object], server_id: str) -> str | None:
        for channel_id, group in cls._groups(document).items():
            if isinstance(group, dict) and server_id in group.get("server_ids", []):
                return channel_id
        return None

    @staticmethod
    def _require(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
