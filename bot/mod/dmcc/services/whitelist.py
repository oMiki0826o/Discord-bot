"""bot/mod/dmcc/services/whitelist.py
Safe construction for the upstream Minecraft whitelist proxy.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import re


_PLAYER_NAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def whitelist_add_command(player_name: str) -> str:
    """Return one native MC command, accepting only a valid Java-edition name."""

    if not isinstance(player_name, str) or not _PLAYER_NAME.fullmatch(player_name):
        raise ValueError("player_name must be 3-16 ASCII letters, digits, or underscores")
    return f"whitelist add {player_name}"
