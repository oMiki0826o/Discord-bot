"""bot/mod/dmcc/services/stats.py
Presentation boundary for authoritative player statistics supplied by a Bridge.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations


def render_stats_response(response: dict[str, object], *, maximum_entries: int = 20) -> str:
    """Render a bounded, descending DMCC statistics leaderboard for Discord."""

    stat_type = response.get("stat_type")
    stat = response.get("stat")
    entries = response.get("entries")
    if not isinstance(stat_type, str) or not stat_type:
        raise ValueError("stats response has no stat_type")
    if not isinstance(stat, str) or not stat:
        raise ValueError("stats response has no stat")
    if not isinstance(entries, list):
        raise ValueError("stats response has invalid entries")
    valid: list[tuple[str, int]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("player_name")
        value = entry.get("value")
        if isinstance(name, str) and name and type(value) is int and value > 0:
            valid.append((name, value))
    valid.sort(key=lambda item: (-item[1], item[0].casefold()))
    if not valid:
        return f"No recorded stats for `{stat_type}` / `{stat}`."
    lines = [f"Stats: `{stat_type}` / `{stat}`"]
    lines.extend(f"{index}. {name} — {value}" for index, (name, value) in enumerate(valid[:maximum_entries], start=1))
    return "\n".join(lines)
