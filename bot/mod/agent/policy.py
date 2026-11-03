"""
bot/mod/agent/policy.py

Modification():
- Parse high-privilege Discord user IDs, without relying on message text.
- Keep administrator privileges separate from private-data access.
"""
from __future__ import annotations

import re

_ID_RE = re.compile(r"^(?:<@!?(\d{1,20})>|(\d{1,20}))$")


def normalize_discord_id(raw: str | int) -> int:
    """Accept user mentions and numeric IDs, rejecting role and broadcast mentions."""
    if isinstance(raw, bool):
        raise ValueError("Invalid Discord user ID")
    value = str(raw).strip()
    match = _ID_RE.fullmatch(value)
    if match is None:
        raise ValueError("Invalid Discord user ID")
    result = int(match.group(1) or match.group(2))
    if not 0 < result <= 2**64 - 1:
        raise ValueError("Invalid Discord user ID")
    return result


def normalize_privileged_users(raw: list[str] | tuple[str, ...]) -> tuple[int, ...]:
    if not isinstance(raw, (list, tuple)) or len(raw) > 25:
        raise ValueError("Invalid privileged user list")
    return tuple(dict.fromkeys(normalize_discord_id(user) for user in raw))
