"""bot/mod/dmcc/repositories/state.py
Persistent Discord channel mappings for configured Minecraft servers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from pathlib import Path

from .json_file import AtomicJsonFile


def _validate(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("DMCC state must be an object")
    mappings = value.get("channel_mappings")
    if not isinstance(mappings, dict) or any(
        not isinstance(server_id, str) or not isinstance(channel_id, str)
        for server_id, channel_id in mappings.items()
    ):
        raise ValueError("channel_mappings must contain string IDs")
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
        mappings = self._mappings(document)
        owner = next((key for key, value in mappings.items() if value == channel_id), None)
        if owner is not None and owner != server_id:
            raise ValueError("channel_id is already mapped to another server")
        mappings[server_id] = channel_id
        self._file.write(document)

    def channel_for_server(self, server_id: str) -> str | None:
        return self._mappings(self._read()).get(server_id)

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
        return len(self._mappings(self._read()))

    def _read(self) -> dict[str, object]:
        return self._file.read({"channel_mappings": {}})

    @staticmethod
    def _mappings(document: dict[str, object]) -> dict[str, str]:
        mappings = document["channel_mappings"]
        assert isinstance(mappings, dict)
        return mappings

    @staticmethod
    def _require(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
