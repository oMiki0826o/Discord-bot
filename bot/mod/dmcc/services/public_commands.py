"""Public player-command privacy filters, independent of Minecraft-side allowlisting."""
from __future__ import annotations

import re

_PRIVATE_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PINGS = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_TELLRAW = re.compile(r"^/?tellraw\s+@a\s+\S[\s\S]*$", re.IGNORECASE)


def sanitize_public_player_command(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 1500:
        return None
    if _PRIVATE_CONTROL.search(value):
        return None
    command = value.strip()
    command = command[1:] if command.startswith("/") else command
    root, separator, remainder = command.partition(" ")
    root = root.casefold()
    if root in {"say", "me"}:
        if not separator or not remainder.strip():
            return None
    elif root == "list":
        if separator:
            return None
    elif root == "tellraw":
        if not _TELLRAW.fullmatch(command):
            return None
    else:
        return None
    return "/" + _PINGS.sub(
        lambda match: f"[{match.group(1).lower()}]", command,
    )
