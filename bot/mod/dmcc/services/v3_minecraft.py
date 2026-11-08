"""bot/mod/dmcc/services/v3_minecraft.py

Modification():

- Parse Minecraft-origin chat to Discord-ready text with explicit alias maps.
- Preserve private message boundaries; neutralize mass mentions and cap payloads.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import urlsplit
import unicodedata
import re

_ALIAS = re.compile(r"(?<![A-Za-z0-9_]):([A-Za-z0-9_]{1,32}):(?![A-Za-z0-9_])")
_USER = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]{3,32})(?![A-Za-z0-9_])")
_MASS = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TIMESTAMP = re.compile(r"<t:(-?[0-9]{1,12})(?::[tTdDfFRsS])?>")
_LINK = re.compile(r"(https?://[^\s<>]{1,512})")
_MARKUP = re.compile(r"([\\\\*_`~|>])")


def format_minecraft_message(
    raw: object, *, emoji_aliases: Mapping[str, str] | None = None,
    mention_ids: Mapping[str, str] | None = None,
    custom_emojis: bool = True, mentions: bool = True,
    unicode_emojis: bool = True, timestamps: bool = True,
    markdown: bool = True, hyperlinks: bool = True, limit: int = 1700,
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
    if timestamps:
        def replace_timestamp(match: re.Match[str]) -> str:
            try:
                return datetime.fromtimestamp(int(match.group(1)), tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M UTC"
                )
            except (ValueError, OSError, OverflowError):
                return "[timestamp]"
        source = _TIMESTAMP.sub(replace_timestamp, source)
    if not unicode_emojis:
        source = "".join(
            "[emoji]" if unicodedata.category(char) == "So" and ord(char) >= 0x2600
            else char for char in source
        )
    if not hyperlinks:
        source = _LINK.sub("[link]", source)
    if not markdown:
        source = _MARKUP.sub(r"\\\1", source)
    if mentions:
        users = mention_ids or {}
        source = _USER.sub(
            lambda m: f"<@{users[m.group(1).casefold()]}>" if m.group(1).casefold() in users
            else m.group(0),
            source,
        )
    return source[:max(1, min(limit, 1900))]
