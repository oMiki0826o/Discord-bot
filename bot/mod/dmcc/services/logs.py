"""bot/mod/dmcc/services/logs.py
Safe presentation helpers for Bridge-returned Minecraft log excerpts.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations


def render_log_excerpt(content: str, *, maximum_characters: int = 1_800) -> str:
    """Bound log text to Discord's message limits and prevent code-fence escape."""

    if not isinstance(content, str):
        raise ValueError("log content must be text")
    if maximum_characters < 1:
        raise ValueError("maximum_characters must be positive")
    truncated = len(content) > maximum_characters
    excerpt = content[:maximum_characters].replace("```", "``\u200b`")
    prefix = "(truncated)\n" if truncated else ""
    return f"{prefix}```text\n{excerpt}\n```"
