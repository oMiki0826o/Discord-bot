"""bot/mod/dmcc/repositories/links.py
The sole JSON source of truth for Discord to Minecraft account links.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.models import AccountLink
from .json_file import AtomicJsonFile


def _validate(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("account links must be an object")
    seen_uuids: set[str] = set()
    for discord_id, entries in value.items():
        if not isinstance(discord_id, str) or not isinstance(entries, list):
            raise ValueError("unsupported account links schema")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("account link entries must be objects")
            minecraft_uuid = entry.get("minecraftUuid")
            player_name = entry.get("playerName")
            if not isinstance(minecraft_uuid, str) or not minecraft_uuid.strip():
                raise ValueError("minecraftUuid must be non-empty")
            if not isinstance(player_name, str) or not player_name.strip():
                raise ValueError("playerName must be non-empty")
            if minecraft_uuid in seen_uuids:
                raise ValueError("minecraft UUID must be globally unique")
            seen_uuids.add(minecraft_uuid)
    return value


class JsonLinkRepository:
    def __init__(self, path: Path) -> None:
        self._file = AtomicJsonFile(path, _validate)

    def link(self, discord_user_id: str, minecraft_uuid: str, minecraft_name: str) -> AccountLink:
        self._require(discord_user_id, "discord_user_id")
        self._require(minecraft_uuid, "minecraft_uuid")
        self._require(minecraft_name, "minecraft_name")
        document = self._read()
        existing = self.discord_for_minecraft(minecraft_uuid, document)
        if existing is not None and existing != discord_user_id:
            raise ValueError("minecraft UUID is already linked to another Discord user")
        entries = document.setdefault(discord_user_id, [])
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            if entry["minecraftUuid"] == minecraft_uuid:
                return AccountLink(discord_user_id, minecraft_uuid, str(entry["playerName"]))
        entries.append({"minecraftUuid": minecraft_uuid, "playerName": minecraft_name})
        self._file.write(document)
        return AccountLink(discord_user_id, minecraft_uuid, minecraft_name)

    def unlink(self, discord_user_id: str, minecraft_uuid: str) -> bool:
        document = self._read()
        entries = document.get(discord_user_id, [])
        assert isinstance(entries, list)
        remaining = [entry for entry in entries if entry["minecraftUuid"] != minecraft_uuid]
        if len(remaining) == len(entries):
            return False
        if remaining:
            document[discord_user_id] = remaining
        else:
            del document[discord_user_id]
        self._file.write(document)
        return True

    def unlink_minecraft(self, minecraft_uuid: str) -> bool:
        discord_user_id = self.discord_for_minecraft(minecraft_uuid)
        return discord_user_id is not None and self.unlink(discord_user_id, minecraft_uuid)

    def links_for_discord(self, discord_user_id: str) -> tuple[AccountLink, ...]:
        entries = self._read().get(discord_user_id, [])
        assert isinstance(entries, list)
        return tuple(
            AccountLink(discord_user_id, str(entry["minecraftUuid"]), str(entry["playerName"]))
            for entry in entries
        )

    def all_links(self) -> tuple[AccountLink, ...]:
        return tuple(
            AccountLink(discord_id, str(entry["minecraftUuid"]), str(entry["playerName"]))
            for discord_id, entries in self._read().items()
            for entry in entries
        )

    def discord_for_minecraft(
        self,
        minecraft_uuid: str,
        document: dict[str, object] | None = None,
    ) -> str | None:
        source = self._read() if document is None else document
        for discord_id, entries in source.items():
            assert isinstance(entries, list)
            if any(entry["minecraftUuid"] == minecraft_uuid for entry in entries):
                return discord_id
        return None

    def _read(self) -> dict[str, object]:
        return self._file.read({})

    @staticmethod
    def _require(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty")
