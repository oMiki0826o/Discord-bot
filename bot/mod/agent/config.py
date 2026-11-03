"""
bot/mod/agent/config.py

Modification():

- 建立 Agent-owned turn、tool 與 timeout budget 設定。

本檔不包含 AI Provider、Memory 或 Database 設定。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .policy import normalize_discord_id, normalize_privileged_users

SETTINGS_NAME = "agent"


def _valid_privileged_users(value: object) -> bool:
    try:
        normalize_privileged_users(value)
        return True
    except ValueError:
        return False


DEFAULT_SETTINGS: dict[str, Any] = {
    "max_model_turns": 4,
    "max_tool_calls": 6,
    "total_timeout_seconds": 45.0,
    "tool_timeout_seconds": 12.0,
    "privileged_users": [],
}


def build_settings_schema(rule_type) -> dict[str, Any]:
    """建立最新版 Core Settings schema，避免 package import 時依賴 Core。"""

    return {
        "max_model_turns": rule_type(int, minimum=1, maximum=16),
        "max_tool_calls": rule_type(int, minimum=1, maximum=32),
        "total_timeout_seconds": rule_type((int, float), minimum=1, maximum=300),
        "tool_timeout_seconds": rule_type((int, float), minimum=0.1, maximum=120),
        "privileged_users": rule_type(list, validator=lambda value: _valid_privileged_users(value)),
    }


@dataclass(frozen=True, slots=True)
class AgentSettings:
    max_model_turns: int
    max_tool_calls: int
    total_timeout_seconds: float
    tool_timeout_seconds: float
    privileged_users: tuple[int, ...] = ()

    def is_privileged(self, user_id: str | int) -> bool:
        return normalize_discord_id(user_id) in self.privileged_users

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "AgentSettings":
        return cls(
            max_model_turns=int(raw["max_model_turns"]),
            max_tool_calls=int(raw["max_tool_calls"]),
            total_timeout_seconds=float(raw["total_timeout_seconds"]),
            tool_timeout_seconds=float(raw["tool_timeout_seconds"]),
            privileged_users=normalize_privileged_users(raw.get("privileged_users", [])),
        )

    def __post_init__(self) -> None:
        if self.max_model_turns < 1 or self.max_tool_calls < 1:
            raise ValueError("Agent turn/tool budget must be positive")
        if self.total_timeout_seconds <= 0:
            raise ValueError("Agent total timeout must be positive")
        if not 0 < self.tool_timeout_seconds <= self.total_timeout_seconds:
            raise ValueError("Agent tool timeout exceeds total timeout")
