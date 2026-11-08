"""bot/mod/dmcc/services/message_format.py

Modification():

- Render Discord mentions, media metadata, poll summaries, and custom emoji
  into bounded Minecraft-compatible plain text without triggering mentions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit

_MENTIONS = re.compile(r"<(@!?|@&|#)([0-9]{15,22})>")
_EMOJI = re.compile(r"<a?:([A-Za-z0-9_]{1,32}):[0-9]{15,22}>")
_TIMESTAMP = re.compile(r"<t:(-?[0-9]{1,12})(?::[tTdDfFRsS])?>")
_PINGS = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_MAX_OUTPUT = 1700


def _clean(text: object, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    return _CONTROL.sub("", text.replace("\r", " ")).strip()[:limit]


def format_discord_content(
    content: str,
    *,
    mentions: Mapping[str, str] | None = None,
    limit: int = 1600,
    custom_emojis: bool = True,
    timestamps: bool = True,
) -> str:
    """Render Discord-specific inline tags as readable MC text, not raw IDs.

    The map is passed from Discord event metadata, never resolved via
    authenticated remote requests or trusted as an authorization grant.
    """
    if not isinstance(content, str):
        return ""
    resolved = mentions or {}

    def mention(match: re.Match[str]) -> str:
        prefix, snowflake = match.group(1), match.group(2)
        label = _clean(resolved.get(snowflake), 48)
        if prefix == "#":
            return f"#{label}" if label else "#channel"
        if prefix == "@&":
            return f"@{label}" if label else "@role"
        return f"@{label}" if label else "@user"

    def time_stamp(match: re.Match[str]) -> str:
        try:
            timestamp = int(match.group(1))
            date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return date.strftime("%Y-%m-%d %H:%M UTC")
        except (OverflowError, OSError, ValueError):
            return "[timestamp]"

    result = _MENTIONS.sub(mention, content)
    if custom_emojis:
        result = _EMOJI.sub(lambda match: f":{match.group(1)}:", result)
    if timestamps:
        result = _TIMESTAMP.sub(time_stamp, result)
    result = _PINGS.sub(lambda match: f"[{match.group(1).lower()}]", result)
    return _clean(result, min(max(1, limit), 2000))


def _safe_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 1500:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return _clean(value, 300)


def render_extras(
    *,
    attachments: Sequence[tuple[str, str]] = (),
    stickers: Sequence[str] = (),
    embeds: Sequence[tuple[str, str]] = (),
    poll: tuple[str, Sequence[str]] | None = None,
) -> str:
    """Bounded readable metadata; never fetch remote media or run HTML."""
    parts: list[str] = []
    for filename, url in tuple(attachments)[:5]:
        name, link = _clean(filename, 80), _safe_url(url)
        if link:
            parts.append(f"Attachment: {name or 'file'} — {link}")
    for sticker in tuple(stickers)[:3]:
        name = _clean(sticker, 80)
        if name:
            parts.append(f"Sticker: {name}")
    for title, url in tuple(embeds)[:3]:
        name, link = _clean(title, 90), _safe_url(url)
        if name or link:
            parts.append(f"Embed: {name or 'embed'}" + (f" — {link}" if link else ""))
    if poll is not None:
        question, options = poll
        q = _clean(question, 150)
        if q:
            answers = ", ".join(_clean(opt, 40) for opt in tuple(options)[:10] if isinstance(opt, str))
            parts.append(f"Poll: {q}" + (f" [{answers}]" if answers else ""))
    return "\n".join(parts)[:_MAX_OUTPUT]
