"""bot/mod/dmcc/services/linking.py
Minecraft-first, one-time DMCC account linking.

The pending verification code is intentionally runtime-only, matching upstream
DMCC v3.  A confirmed association is written to ``links.json`` by
``JsonLinkStore``; it is not duplicated in any database or secondary store.


Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..domain.models import AccountLink
from ..repositories.links import JsonLinkRepository


@dataclass(frozen=True, slots=True)
class PendingLink:
    """A Minecraft player waiting for the Discord-side ``/dmcc link`` action."""

    code: str
    minecraft_uuid: str
    minecraft_name: str
    expires_at: datetime


class LinkingService:
    """Generate MC-first verification codes, then bind them to Discord users."""

    _ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(
        self,
        *,
        now_provider: Callable[[], datetime] | None = None,
        code_factory: Callable[[], str] | None = None,
        code_lifetime: timedelta = timedelta(minutes=5),
        link_store: JsonLinkRepository | None = None,
    ) -> None:
        if code_lifetime <= timedelta():
            raise ValueError("code_lifetime must be positive")
        if link_store is None:
            raise ValueError("link_store is required; links.json is the account source of truth")
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._code_factory = code_factory or self._new_code
        self._code_lifetime = code_lifetime
        self._link_store = link_store
        self._by_code: dict[str, PendingLink] = {}
        self._code_by_uuid: dict[str, str] = {}

    def begin_minecraft_link(self, minecraft_uuid: str, minecraft_name: str) -> str:
        """Issue or refresh the six-character code for one Minecraft UUID."""

        self._require(minecraft_uuid, "minecraft_uuid")
        self._require(minecraft_name, "minecraft_name")
        previous = self._code_by_uuid.pop(minecraft_uuid, None)
        if previous is not None:
            self._by_code.pop(previous, None)
        code = self._unique_code()
        pending = PendingLink(code, minecraft_uuid, minecraft_name, self._now() + self._code_lifetime)
        self._by_code[code] = pending
        self._code_by_uuid[minecraft_uuid] = code
        return code

    def confirm_discord_link(self, code: str, discord_user_id: str) -> AccountLink | None:
        """Consume a valid code and persist the resulting relationship to JSON."""

        self._require(code, "code")
        self._require(discord_user_id, "discord_user_id")
        pending = self._by_code.pop(code.upper(), None)
        if pending is None:
            return None
        self._code_by_uuid.pop(pending.minecraft_uuid, None)
        if pending.expires_at <= self._now():
            return None
        return self._link_store.link(discord_user_id, pending.minecraft_uuid, pending.minecraft_name)

    def links_for_discord(self, discord_user_id: str) -> tuple[AccountLink, ...]:
        """List this Discord user's linked accounts for the upstream ``links`` command."""

        self._require(discord_user_id, "discord_user_id")
        return self._link_store.links_for_discord(discord_user_id)

    def unlink_discord(self, discord_user_id: str) -> int:
        """Remove every account belonging to a Discord user, like upstream Discord ``unlink``."""

        links = self.links_for_discord(discord_user_id)
        for link in links:
            self._link_store.unlink(discord_user_id, link.minecraft_uuid)
        return len(links)

    def unlink_minecraft(self, minecraft_uuid: str) -> bool:
        """Remove a player-owned association requested from the Minecraft side."""

        self._require(minecraft_uuid, "minecraft_uuid")
        return self._link_store.unlink_minecraft(minecraft_uuid)

    def _unique_code(self) -> str:
        for _ in range(10):
            code = self._code_factory().upper()
            if len(code) == 6 and all(character in self._ALPHABET for character in code) and code not in self._by_code:
                return code
        raise RuntimeError("could not generate a unique DMCC verification code")

    def _now(self) -> datetime:
        now = self._now_provider()
        if now.tzinfo is None:
            raise ValueError("now_provider must return a timezone-aware datetime")
        return now.astimezone(UTC)

    def _new_code(self) -> str:
        return "".join(secrets.choice(self._ALPHABET) for _ in range(6))

    @staticmethod
    def _require(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty")
