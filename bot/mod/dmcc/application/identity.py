"""bot/mod/dmcc/application/identity.py
Preview-and-confirm import of DiscordSRV account links.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from ..domain.errors import ImportConflict, ServerNotFound
from ..repositories.links import JsonLinkRepository


@dataclass(frozen=True, slots=True)
class ImportPreview:
    preview_id: str
    server_id: str
    source_hash: str
    additions: int
    conflicts: tuple[str, ...]
    skipped: tuple[str, ...]
    entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ImportResult:
    added: int
    conflicts: tuple[str, ...]


class DiscordSrvImportService:
    def __init__(self, sources: Mapping[str, object], links: JsonLinkRepository) -> None:
        self._sources = dict(sources)
        self._links = links
        self._previews: dict[str, ImportPreview] = {}

    async def preview(self, server_id: str) -> ImportPreview:
        source = self._sources.get(server_id)
        if source is None:
            raise ServerNotFound(f"no DiscordSRV import source for {server_id}")
        content = await source.read_links()
        if not isinstance(content, str):
            raise ImportConflict("DiscordSRV source is not text")
        additions: list[tuple[str, str]] = []
        skipped: list[str] = []
        conflicts: list[str] = []
        seen: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = [part.strip() for part in stripped.split(":")]
            if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
                skipped.append(stripped)
                continue
            try:
                minecraft_uuid = str(uuid.UUID(parts[0]))
            except ValueError:
                skipped.append(stripped)
                continue
            if minecraft_uuid in seen:
                skipped.append(stripped)
                continue
            seen.add(minecraft_uuid)
            owner = self._links.discord_for_minecraft(minecraft_uuid)
            if owner is not None and owner != parts[1]:
                conflicts.append(minecraft_uuid)
                continue
            if owner is None:
                additions.append((parts[1], minecraft_uuid))
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        preview_id = hashlib.sha256(f"{server_id}:{source_hash}".encode("utf-8")).hexdigest()[:24]
        preview = ImportPreview(preview_id, server_id, source_hash, len(additions), tuple(conflicts), tuple(skipped), tuple(additions))
        self._previews[preview_id] = preview
        return preview

    async def apply(self, preview_id: str, owner_id: str) -> ImportResult:
        if not owner_id:
            raise ImportConflict("import owner is required")
        preview = self._previews.pop(preview_id, None)
        if preview is None:
            raise ImportConflict("import preview is missing or expired")
        source = self._sources[preview.server_id]
        current = await source.read_links()
        if hashlib.sha256(current.encode("utf-8")).hexdigest() != preview.source_hash:
            raise ImportConflict("source changed since preview")
        conflicts = list(preview.conflicts)
        added = 0
        for discord_id, minecraft_uuid in preview.entries:
            existing = self._links.discord_for_minecraft(minecraft_uuid)
            if existing is not None and existing != discord_id:
                conflicts.append(minecraft_uuid)
                continue
            if existing is None:
                self._links.link(discord_id, minecraft_uuid, minecraft_uuid)
                added += 1
        return ImportResult(added, tuple(conflicts))
