"""bot/mod/dmcc/services/info.py

bot/mod/dmcc/dmcc/services/info.py

Modification():

- 移植 upstream DMCC `help` / `info` 的資料層，供 Discord 與 Minecraft 入口共用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..repositories.state import JsonStateRepository
from .command_catalog import CommandCatalog


# ── Protocols and Models ──────────────────────


class _ConnectionManager(Protocol):
    def all(self) -> tuple[object, ...]: ...


class _Gateway(Protocol):
    manager: _ConnectionManager


@dataclass(frozen=True, slots=True)
class DmccInfo:
    """適合 Discord `/info` 格式化的 Module 狀態快照。"""

    online_server_ids: tuple[str, ...]
    channel_mappings: int


# ── Service ──────────────────────


class InfoService:
    """提供 upstream DMCC 動態 help 與無 Discord 依賴的 status report。"""

    def __init__(self, gateway: _Gateway, repository: JsonStateRepository, catalog: CommandCatalog) -> None:
        self._gateway = gateway
        self._repository = repository
        self._catalog = catalog

    def help_for(self, op_level: int) -> tuple[str, ...]:
        """依委派 OP level 回傳可見 command 名稱。"""

        return self._catalog.available_names(op_level)

    def report(self) -> DmccInfo:
        """取得目前 Bridge 與頻道映射的狀態快照。"""

        server_ids = sorted(
            str(connection.server_id)
            for connection in self._gateway.manager.all()
            if getattr(connection, "server_id", None) is not None
        )
        return DmccInfo(tuple(server_ids), self._repository.channel_mapping_count())
