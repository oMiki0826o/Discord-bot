"""bot/mod/mc_backup/application/operations.py

Per-server serialization for destructive local maintenance.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import asyncio


class OperationLockPool:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def for_server(self, server_id: str) -> asyncio.Lock:
        if not server_id.strip():
            raise ValueError("server_id must be non-empty")
        return self._locks.setdefault(server_id, asyncio.Lock())
