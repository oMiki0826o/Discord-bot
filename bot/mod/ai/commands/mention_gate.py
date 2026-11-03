"""
bot/mod/ai/commands/mention_gate.py

Only a direct leading mention of the real bot may trigger conversational AI.
Modification():
- Strengthen AI/Agent correctness and compatibility.
"""
from __future__ import annotations
import re


def parse_direct_mention(content: str, bot_user_id: int) -> str | None:
    """Return the prompt for an explicit leading <@id>/<@!id>, otherwise None."""
    if bot_user_id <= 0:
        return None
    # Leading quoted text, role mentions, and broadcasts are not bot requests.
    match = re.match(rf"^\s*<@!?{bot_user_id}>(?:\s+|$)", content)
    if match is None:
        return None
    return content[match.end():].strip()
