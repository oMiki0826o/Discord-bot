"""tools/import_legacy_dmcc.py
Convert legacy Discord-MC-Chat JSON into DMCC v3 configuration fragments.

The converter never copies Discord tokens, webhook URLs, or administrator IDs.
It writes no files unless the caller redirects its JSON output.

Modification():
- Convert legacy DMCC JSON into safe configuration fragments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from string import Formatter
from typing import Any


def _discord_id(value: object) -> str | None:
    return value if isinstance(value, str) and value.isascii() and value.isdecimal() and 15 <= len(value) <= 20 else None


def _mspt_limit(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 65.0
    return float(value) if 1 <= float(value) <= 2000 else 65.0


_TEMPLATE_FIELDS = {
    "player", "server", "message", "death_message", "game_mode", "title", "label",
    "description", "advancement_type", "minecraft_uuid", "minecraft_version", "motd",
    "online_players", "max_players",
}


def _template(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_000:
        return None
    try:
        for _, field, spec, conversion in Formatter().parse(value):
            if field is not None and (field not in _TEMPLATE_FIELDS or spec or conversion):
                return None
    except ValueError:
        return None
    return value


def _label(value: object, server_id: str) -> str:
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 60:
        return value.strip()
    return server_id[:60] if server_id[:60].strip() else "Minecraft"


def migrate(records: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    """Return safe DMCC settings and state fragments from legacy server settings."""
    monitoring: dict[str, dict[str, Any]] = {}
    presentation: dict[str, dict[str, Any]] = {}
    console: dict[str, dict[str, str]] = {}
    groups: dict[str, list[str]] = {}
    legacy_avatar_api = False
    for server_id, label, raw in records:
        label = _label(label, server_id)
        generic = raw.get("generic", {}) if isinstance(raw.get("generic"), dict) else {}
        custom = raw.get("customMessage", {}) if isinstance(raw.get("customMessage"), dict) else {}
        channel_id = _discord_id(generic.get("channelId"))
        legacy_avatar_api = legacy_avatar_api or bool(generic.get("avatarApi"))
        if channel_id is not None:
            groups.setdefault(channel_id, []).append(server_id)
        console_id = _discord_id(generic.get("consoleLogChannelId"))
        if console_id is not None:
            console[server_id] = {"channel_id": console_id}
        templates = {
            "server_started": custom.get("serverStarted", ""),
            "server_stopping": custom.get("serverStopped", ""),
            "player_join": custom.get("joinServer", ""),
            "player_quit": custom.get("leftServer", ""),
            "player_death": custom.get("deathMessage", ""),
            "player_advancement": custom.get("advancementTask", ""),
        }
        presentation[server_id] = {
            "label": label, "locale": "zh_TW",
            "templates": {k: safe for k, v in templates.items() if (safe := _template(v)) is not None},
        }
        monitoring[server_id] = {
            "label": label,
            "mspt_threshold": _mspt_limit(generic.get("msptLimit", 65)),
            "alert_channel_id": channel_id if generic.get("announceHighMspt") else None,
            "topic_channel_id": channel_id if generic.get("updateChannelTopic") else None,
            "status_voice_channel_id": None,
        }
    state_groups = {channel_id: {"server_ids": server_ids, "replies": True, "attachments": True, "stickers": True, "custom_emojis": True, "embeds": False, "polls": False, "components": False, "edits": False, "deletes": False, "reactions": False} for channel_id, server_ids in groups.items() if len(server_ids) > 1}
    singles = {server_ids[0]: channel_id for channel_id, server_ids in groups.items() if len(server_ids) == 1}
    return {"dmcc": {
        "monitoring": {"enabled": any(item["alert_channel_id"] is not None for item in monitoring.values()), "presence": True, "servers": monitoring},
        "presentation": {"servers": presentation},
        "console_stream": {"enabled": bool(console), "servers": console},
        # Legacy DMCC requested mc-heads by default, so preserve that intent
        # while keeping the new network probe explicit and independently switchable.
        "avatar_refresh": {"enabled": legacy_avatar_api, "source": "fabric"},
        "private_messages": {"enabled": False},
    }, "state": {"channel_mappings": singles, "channel_groups": state_groups}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create safe DMCC v3 fragments from legacy DMCC JSON")
    parser.add_argument("--server", action="append", required=True, metavar="ID:LABEL:PATH")
    args = parser.parse_args()
    records = []
    for item in args.server:
        server_id, label, raw_path = item.split(":", 2)
        records.append((server_id, label, json.loads(Path(raw_path).read_text(encoding="utf-8"))))
    print(json.dumps(migrate(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
