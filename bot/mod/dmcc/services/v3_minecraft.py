"""bot/mod/dmcc/services/v3_minecraft.py

Modification():

- Parse Minecraft-origin chat to Discord-ready text with explicit alias maps.
- Preserve private message boundaries; neutralize mass mentions and cap payloads.
"""
from __future__ import annotations

from collections.abc import Mapping
import re

_ALIAS = re.compile(r"(?<![A-Za-z0-9_]):([A-Za-z0-9_]{1,32}):(?![A-Za-z0-9_])")
_USER = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]{3,32})(?![A-Za-z0-9_])")
_MASS = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def format_minecraft_message(
    raw: object, *, emoji_aliases: Mapping[str, str] | None = None,
    mention_ids: Mapping[str, str] | None = None,
    custom_emojis: bool = True, mentions: bool = True, limit: int = 1700,
) -> str:
    if not isinstance(raw, str):
        return ""
    source = _CONTROL.sub(" ", raw)[:min(10_000, max(1, limit * 4))]
    source = _MASS.sub(lambda m: f"[{m.group(1).lower()}]", source)
    if custom_emojis:
        emoji = emoji_aliases or {}
        source = _ALIAS.sub(
            lambda m: emoji.get(m.group(1).casefold(), m.group(0)), source
        )
    if mentions:
        users = mention_ids or {}
        source = _USER.sub(
            lambda m: f"<@{users[m.group(1).casefold()]}>" if m.group(1).casefold() in users
            else m.group(0),
            source,
        )
    return source[:max(1, min(limit, 1900))]
