"""bot/mod/dmcc/services/mentions.py

Modification():

- Opt-in linked-player notifications for Discord user mentions. Only explicit user mentions in an already mapped bridge channel are eligible. There are no mass, role, or everyone notifications; the authenticated Fabric bridge receives UUIDs r
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import logging
import re
import time

_LOGGER = logging.getLogger(__name__)
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_SNOWFLAKE = re.compile(r"^[0-9]{15,20}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class MentionConfig:
    enabled: bool = False
    style: str = "actionbar"
    max_targets: int = 8
    cooldown_seconds: int = 15
    sound: bool = True
    role_mentions: bool = False

    @classmethod
    def from_mapping(cls, raw: object) -> "MentionConfig":
        if not isinstance(raw, Mapping) or set(raw) - {
            "enabled", "style", "max_targets", "cooldown_seconds", "sound", "role_mentions"
        }:
            raise ValueError("mentions has invalid fields")
        enabled, style = raw.get("enabled", False), raw.get("style", "actionbar")
        max_targets = raw.get("max_targets", 8)
        cooldown = raw.get("cooldown_seconds", 15)
        sound = raw.get("sound", True)
        role_mentions = raw.get("role_mentions", False)
        if (type(enabled) is not bool or style not in {"chat", "actionbar", "title"} or type(sound) is not bool or type(role_mentions) is not bool
                or type(max_targets) is not int or not 1 <= max_targets <= 16
                or type(cooldown) is not int or not 1 <= cooldown <= 3600):
            raise ValueError("invalid mentions policy")
        return cls(enabled, style, max_targets, cooldown, sound, role_mentions)


class MinecraftMentionService:
    def __init__(
        self, config: MentionConfig, state: object, links: object, sender: object,
        *, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._state, self._links, self._sender = state, links, sender
        self._clock = clock
        self._last: dict[tuple[str, str], float] = {}

    async def notify(
        self, channel_id: str, author_name: str, content: str,
        mentioned_discord_ids: Sequence[str],
    ) -> bool:
        if not self.config.enabled or not isinstance(channel_id, str):
            return False
        server_id = self._state.server_for_channel(channel_id)
        if server_id is None:
            return False
        now = self._clock()
        if len(self._last) > 4096:
            self._last = {
                pair: at for pair, at in self._last.items()
                if now - at < self.config.cooldown_seconds
            }
        uuids: list[str] = []
        allowed: list[tuple[str, str]] = []
        seen: set[str] = set()
        for user in mentioned_discord_ids[:64]:
            if not isinstance(user, str) or not _SNOWFLAKE.fullmatch(user):
                continue
            for link in self._links.links_for_discord(user):
                uuid = link.minecraft_uuid
                if (not isinstance(uuid, str) or not _UUID.fullmatch(uuid)
                        or uuid in seen):
                    continue
                key = (server_id, uuid)
                previous = self._last.get(key)
                if previous is not None and now - previous < self.config.cooldown_seconds:
                    continue
                seen.add(uuid)
                uuids.append(uuid)
                allowed.append(key)
                if len(uuids) >= self.config.max_targets:
                    break
            if len(uuids) >= self.config.max_targets:
                break
        if not uuids:
            return False
        author = _CONTROL.sub(" ", author_name)[:64] if isinstance(author_name, str) else "Discord"
        message = _CONTROL.sub(" ", content)[:160] if isinstance(content, str) else ""
        data = {
            "player_uuids": uuids,
            "style": self.config.style,
            "sound": self.config.sound,
            "message": f"{author} 在 Discord 提及了你：" + message,
        }
        try:
            await self._sender.send_packet(server_id, "player_mention", None, data)
        except (ConnectionError, LookupError, TimeoutError):
            return False
        except Exception:
            _LOGGER.exception("Failed to send DMCC mention notification to %s", server_id)
            return False
        for key in allowed:
            self._last[key] = now
        return True


def collect_role_mention_users(
    guild: object, roles: Sequence[object], *, max_targets: int,
) -> tuple[str, ...]:
    """Resolve explicit role mentions without partial cached-member snapshots.

    All-or-nothing protects against incomplete membership data and accidental
    large notifications. The Discord API is never called from this function.
    """
    if type(max_targets) is not int or not 1 <= max_targets <= 16:
        return ()
    if not roles or len(roles) > 16 or not bool(getattr(guild, "chunked", False)):
        return ()
    members = getattr(guild, "members", None)
    if not isinstance(members, (list, tuple)) or len(members) > 200_000:
        return ()
    targets: set[str] = set()
    for role in roles:
        identity = str(getattr(role, "id", ""))
        if not _SNOWFLAKE.fullmatch(identity):
            return ()
        targets.add(identity)
    found: set[str] = set()
    for member in members:
        if bool(getattr(member, "bot", False)):
            continue
        user_id = str(getattr(member, "id", ""))
        if not _SNOWFLAKE.fullmatch(user_id):
            return ()
        user_roles = getattr(member, "roles", None)
        if not isinstance(user_roles, (list, tuple)):
            return ()
        if any(str(getattr(role, "id", "")) in targets for role in user_roles):
            found.add(user_id)
            if len(found) > max_targets:
                return ()
    return tuple(sorted(found))
