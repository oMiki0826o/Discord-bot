"""bot/mod/dmcc/events.py

bot/mod/dmcc/dmcc/events.py

Modification():

- 定義 Python Gateway 對 Relay Service 發出的 Minecraft 原始事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


# ── Gateway Events ──────────────────────


@dataclass(frozen=True, slots=True)
class MinecraftEvent:
    """已認證 Minecraft Bridge 回報的一個最小事件。"""

    type: str
    server_id: str
    data: Mapping[str, object]
