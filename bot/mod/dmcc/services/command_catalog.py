"""bot/mod/dmcc/services/command_catalog.py

bot/mod/dmcc/dmcc/services/command_catalog.py

Modification():

- 移植 upstream DMCC v3 CommandManager 的模式、參數與 edge-permission 規則。
- 本檔不依賴 Discord.py 或 Minecraft API。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# ── Models ──────────────────────


class DmccMode(StrEnum):
    """與 upstream v3 對齊的 DMCC 部署模式。"""

    SINGLE_SERVER = "single_server"
    STANDALONE = "standalone"
    MULTI_SERVER_CLIENT = "multi_server_client"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """一條 DMCC command 的安全、參數與模式契約。"""

    name: str
    minimum_op_level: int
    required_arguments: int = 0
    accepts_extra_arguments: bool = False
    modes: frozenset[DmccMode] = frozenset(DmccMode)


# ── Catalog ──────────────────────


class CommandCatalog:
    """提供 Discord slash adapter 與 Minecraft handler 共用的 command 規則。"""

    _SPECS = (
        CommandSpec("help", -1),
        CommandSpec("info", -1),
        CommandSpec("server-info", -1, 1),
        CommandSpec("suggest", -1, 2),
        CommandSpec("log", 4, 1),
        CommandSpec("reload", 4),
        CommandSpec("update", -1),
        CommandSpec("console", 0, 1, True, frozenset({DmccMode.SINGLE_SERVER, DmccMode.STANDALONE})),
        CommandSpec("execute", -1, 2, True, frozenset({DmccMode.STANDALONE})),
        CommandSpec("link", 0, modes=frozenset({DmccMode.SINGLE_SERVER, DmccMode.STANDALONE, DmccMode.MULTI_SERVER_CLIENT})),
        CommandSpec("links", 4, modes=frozenset({DmccMode.SINGLE_SERVER, DmccMode.STANDALONE})),
        CommandSpec("unlink", 0, modes=frozenset(DmccMode)),
        CommandSpec("stats", -1, 2, modes=frozenset({DmccMode.SINGLE_SERVER, DmccMode.MULTI_SERVER_CLIENT})),
        CommandSpec("whitelist", 0, 1, modes=frozenset({DmccMode.SINGLE_SERVER, DmccMode.MULTI_SERVER_CLIENT})),
        CommandSpec("shutdown", 4, modes=frozenset({DmccMode.STANDALONE})),
    )

    def __init__(self, mode: DmccMode) -> None:
        self._mode = mode
        self._by_name = {spec.name: spec for spec in self._SPECS if mode in spec.modes}

    def available_names(self, op_level: int) -> tuple[str, ...]:
        """回傳該身分可看到的 help 指令，與 upstream 動態 help 一致。"""

        return tuple(sorted(spec.name for spec in self._by_name.values() if op_level >= spec.minimum_op_level))

    def validate(self, name: str, op_level: int, arguments: tuple[str, ...]) -> str | None:
        """驗證 command 可用性；成功回傳 None，失敗回傳穩定錯誤碼。"""

        spec = self._by_name.get(name.casefold())
        if spec is None:
            return "unknown_command"
        if op_level < spec.minimum_op_level:
            return "insufficient_permission"
        if len(arguments) < spec.required_arguments:
            return "invalid_usage"
        if len(arguments) > spec.required_arguments and not spec.accepts_extra_arguments:
            return "invalid_usage"
        return None
