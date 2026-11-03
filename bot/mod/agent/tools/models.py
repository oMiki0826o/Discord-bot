"""
bot/mod/agent/tools/models.py

Modification():

- 建立 Agent-owned 只讀 Tool 契約、schema validation、capability policy 與 timeout。
- 使用 AI RuntimeRequest 作為 trusted scope，不接受模型指定身分。
- 保存 Provider function call ID，讓 Gemini 3 tool-context circulation 可回傳結果。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Mapping

from ...ai.api import RuntimeRequest

ToolHandler = Callable[[dict[str, Any], "ToolContext"], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    thought_signature: Any = field(default=None, repr=False, compare=False)
    call_id: str = ""

    @property
    def fingerprint(self) -> str:
        payload = json.dumps([self.name, self.arguments], ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolContext:
    request: RuntimeRequest
    capabilities: frozenset[str]
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str = ""
    observation_id: str = ""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    capability: str
    argument_names: frozenset[str]
    handler: ToolHandler = field(repr=False, compare=False)
    required_argument_names: frozenset[str] = frozenset()
    argument_types: Mapping[str, str] = field(default_factory=dict)
    max_output_chars: int = 12_000
    retry_on_empty: bool = False

    def __post_init__(self) -> None:
        if not self.required_argument_names.issubset(self.argument_names):
            raise ValueError("Required tool arguments must be declared")
        if not set(self.argument_types).issubset(self.argument_names):
            raise ValueError("Typed tool arguments must be declared")
        if any(value not in {"string", "integer", "number", "boolean"} for value in self.argument_types.values()):
            raise ValueError("Unsupported tool argument type")
        if self.max_output_chars < 1:
            raise ValueError("Tool output limit must be positive")

    def declaration(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    name: {"type": self.argument_types.get(name, "string")}
                    for name in sorted(self.argument_names)
                },
                "required": sorted(self.required_argument_names),
            },
        }

