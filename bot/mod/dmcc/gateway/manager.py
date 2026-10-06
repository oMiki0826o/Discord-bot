"""bot/mod/dmcc/gateway/manager.py

bot/mod/dmcc/dmcc/gateway/manager.py

Modification():

- 管理已認證的 `server_id → Connection` 對應，防止 Server 身分覆寫。
"""

from __future__ import annotations

from .connection import Connection


# ── Connection Registry ──────────────────────


class ConnectionManager:
    """只保存已認證且目前有效的 Minecraft Bridge 連線。"""

    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}

    def get(self, server_id: str) -> Connection | None:
        """取得目前有效的 Server 連線。"""

        return self._connections.get(server_id)

    def register(self, server_id: str, connection: Connection) -> bool:
        """註冊唯一 Server 連線；ID 已使用時不覆寫。"""

        if server_id in self._connections:
            return False
        self._connections[server_id] = connection
        return True

    def unregister(self, server_id: str | None, connection: Connection) -> None:
        """只在 Registry 仍指向同一連線時移除 Server。"""

        if server_id is not None and self._connections.get(server_id) is connection:
            del self._connections[server_id]

    def all(self) -> tuple[Connection, ...]:
        """回傳目前連線快照，供 Gateway teardown 使用。"""

        return tuple(self._connections.values())
