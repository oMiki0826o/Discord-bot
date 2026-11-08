"""bot/mod/dmcc/services/private_messages.py

Modification():

- Add separately consented Minecraft<->Discord private message transport.
- Route directly to linked recipients, never through public Discord channels.
- Keep message contents out of logs and refuse untrusted packet identities.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from discord import AllowedMentions

from ..events import MinecraftEvent
from ..repositories.json_file import AtomicJsonFile
from ..repositories.links import JsonLinkRepository
from .v3_features import V3FeatureConfig

LOGGER = logging.getLogger(__name__)
_USER = re.compile(r"^[0-9]{15,20}$")
_UUID = re.compile(r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$")
_PLAYER = re.compile(r"^[A-Za-z0-9_]{3,16}$")
_BAD = re.compile(r"[\x00-\x1f\x7f]")


def _validate_consent(raw: object) -> dict[str, bool]:
    if not isinstance(raw, dict) or len(raw) > 100_000:
        raise ValueError("invalid private message consent document")
    if any(not isinstance(key, str) or not _USER.fullmatch(key) or type(value) is not bool
           for key, value in raw.items()):
        raise ValueError("invalid private message consent entry")
    return raw


def safe_private_message(raw: object, *, limit: int = 750) -> str | None:
    if not isinstance(raw, str) or not raw.strip() or _BAD.search(raw):
        return None
    content = raw.strip()
    if len(content) > limit:
        return None
    return re.sub(r"@(everyone|here)\b", lambda m: "[" + m.group(1).lower() + "]", content, flags=re.I)


class PrivateMessageConsent:
    def __init__(self, path: Path) -> None:
        self._file = AtomicJsonFile(path, _validate_consent)

    def enabled(self, discord_id: str) -> bool:
        return bool(self._file.read({}).get(discord_id, False)) if _USER.fullmatch(discord_id) else False

    def set(self, discord_id: str, value: bool) -> None:
        if not _USER.fullmatch(discord_id) or type(value) is not bool:
            raise ValueError("invalid private message consent")
        document = self._file.read({})
        if value:
            document[discord_id] = True
        else:
            document.pop(discord_id, None)
        self._file.write(document)


class DmPrivateMessageService:
    def __init__(
        self, bot: Any, gateway: Any,
        links: JsonLinkRepository, consent: PrivateMessageConsent,
        features: V3FeatureConfig,
    ) -> None:
        self._bot = bot
        self._gateway = gateway
        self._links = links
        self._consent = consent
        self._features = features

    def refresh(self, features: V3FeatureConfig) -> None:
        self._features = features

    def opt_in(self, user_id: str, enabled: bool) -> None:
        # A user cannot opt in before binding an identity to their Discord ID.
        if enabled and not self._links.links_for_discord(user_id):
            raise ValueError("link your Minecraft account first")
        self._consent.set(user_id, enabled)

    async def from_minecraft(self, event: MinecraftEvent) -> bool:
        if event.type != "player_private_message" or not (
            self._features.enabled and self._features.private_messages
        ):
            return False
        source = event.data.get("sender_uuid")
        recipient = event.data.get("recipient_uuid")
        name = event.data.get("sender_name")
        message = safe_private_message(event.data.get("message"))
        if not (isinstance(source, str) and _UUID.fullmatch(source)
                and isinstance(recipient, str) and _UUID.fullmatch(recipient)
                and isinstance(name, str) and _PLAYER.fullmatch(name) and message):
            return False
        from_user = self._links.discord_for_minecraft(source)
        to_user = self._links.discord_for_minecraft(recipient)
        if not from_user or not to_user or not self._consent.enabled(to_user):
            return False
        get_user = getattr(self._bot, "get_user", None)
        user = get_user(int(to_user)) if callable(get_user) else None
        if user is None:
            fetch_user = getattr(self._bot, "fetch_user", None)
            if not callable(fetch_user):
                return False
            try:
                user = await fetch_user(int(to_user))
            except Exception as exc:
                LOGGER.warning("DMCC private recipient lookup failed (%s)", type(exc).__name__)
                return False
        if user is None or not hasattr(user, "send"):
            return False
        try:
            await user.send(
                f"[{event.server_id}] Private Minecraft message from {name}: {message}",
                allowed_mentions=AllowedMentions.none(),
            )
            return True
        except Exception as exc:
            LOGGER.warning("DMCC private Discord delivery failed (%s)", type(exc).__name__)
            return False

    async def from_discord(
        self, user_id: str, server_id: str,
        minecraft_name: str, raw_message: str,
    ) -> bool:
        if not (self._features.enabled and self._features.private_messages):
            return False
        if not _USER.fullmatch(user_id) or not self._links.links_for_discord(user_id):
            return False
        if not isinstance(minecraft_name, str) or not _PLAYER.fullmatch(minecraft_name):
            return False
        message = safe_private_message(raw_message)
        if message is None:
            return False
        recipients = tuple(link for link in self._links.all_links()
                           if link.minecraft_name.casefold() == minecraft_name.casefold())
        if len(recipients) != 1 or not self._consent.enabled(recipients[0].discord_user_id):
            return False
        source_name = self._links.links_for_discord(user_id)[0].minecraft_name
        try:
            result = await self._gateway.requests.request(
                server_id, "minecraft_private_message", {
                    "recipient_uuid": recipients[0].minecraft_uuid,
                    "sender_name": source_name,
                    "message": message,
                },
            )
        except (TimeoutError, ValueError, LookupError, ConnectionError):
            return False
        return isinstance(result, dict) and result.get("ok") is True
