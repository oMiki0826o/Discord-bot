"""bot/mod/dmcc/services/op_levels.py
Resolve DMCC command OP levels from Discord identities and account links.

This mirrors the upstream v3 policy: explicit user and role mappings grant the
highest matching level, a server override can refine that level, and a Discord
user with a linked Minecraft account has the base level ``0``.


Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..repositories.links import JsonLinkRepository


@dataclass(frozen=True, slots=True)
class _Mapping:
    subject: str
    op_level: int
    server_overrides: dict[str, int]

    def level_for(self, server_id: str | None) -> int:
        if server_id is not None and server_id in self.server_overrides:
            return self.server_overrides[server_id]
        return self.op_level


class OpLevelResolver:
    """Apply upstream DMCC identity, role, and linked-account OP semantics."""

    def __init__(
        self,
        user_mappings: Iterable[_Mapping],
        role_mappings: Iterable[_Mapping],
        links: JsonLinkRepository,
    ) -> None:
        self._user_mappings = tuple(user_mappings)
        self._role_mappings = tuple(role_mappings)
        self._links = links

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object], links: JsonLinkRepository) -> "OpLevelResolver":
        """Build a resolver from the module's JSON-safe permission settings."""

        if not isinstance(raw, Mapping):
            raise ValueError("permission settings must be an object")
        return cls(
            cls._parse_mappings(raw.get("user_mappings", []), "user"),
            cls._parse_mappings(raw.get("role_mappings", []), "role"),
            links,
        )

    def resolve(
        self,
        discord_user_id: str,
        role_ids: Iterable[str],
        server_id: str | None,
        *,
        discord_user_name: str | None = None,
        role_names: Iterable[str] = (),
    ) -> int:
        """Return the highest permitted OP level, from ``-1`` through ``4``."""

        identities = {discord_user_id}
        if discord_user_name:
            identities.add(discord_user_name)
        roles = set(role_ids)
        roles.update(role_names)

        levels = [
            mapping.level_for(server_id)
            for mapping in self._user_mappings
            if mapping.subject in identities
        ]
        levels.extend(
            mapping.level_for(server_id)
            for mapping in self._role_mappings
            if mapping.subject in roles
        )
        highest = max(levels, default=-1)
        if highest < 0 and self._links.links_for_discord(discord_user_id):
            return 0
        return highest

    @staticmethod
    def _parse_mappings(raw: object, subject_key: str) -> tuple[_Mapping, ...]:
        if not isinstance(raw, list):
            raise ValueError(f"{subject_key}_mappings must be a list")
        parsed: list[_Mapping] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError(f"{subject_key} mapping must be an object")
            subject = item.get(subject_key)
            op_level = item.get("op_level")
            if not isinstance(subject, str) or not subject.strip():
                raise ValueError(f"{subject_key} mapping requires a non-empty {subject_key}")
            if type(op_level) is not int or not -1 <= op_level <= 4:
                raise ValueError("op_level must be an integer between -1 and 4")
            overrides_raw = item.get("server_overrides", [])
            if not isinstance(overrides_raw, list):
                raise ValueError("server_overrides must be a list")
            overrides: dict[str, int] = {}
            for override in overrides_raw:
                if not isinstance(override, Mapping):
                    raise ValueError("server override must be an object")
                server = override.get("server")
                level = override.get("op_level")
                if not isinstance(server, str) or not server.strip():
                    raise ValueError("server override requires a server")
                if type(level) is not int or not -1 <= level <= 4:
                    raise ValueError("override op_level must be an integer between -1 and 4")
                overrides[server] = level
            parsed.append(_Mapping(subject, op_level, overrides))
        return tuple(parsed)
