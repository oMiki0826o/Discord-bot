"""
bot/mod/agent/tools.py

Modification():

- 建立 Agent-owned 只讀 Tool 契約、schema validation、capability policy 與 timeout。
- 使用 AI RuntimeRequest 作為 trusted scope，不接受模型指定身分。
- 保存 Provider function call ID，讓 Gemini 3 tool-context circulation 可回傳結果。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..ai.api import RuntimeRequest

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


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def declarations(self, capabilities: frozenset[str]) -> tuple[dict[str, object], ...]:
        return tuple(tool.declaration() for tool in self._tools.values() if tool.capability in capabilities)

    def retries_on_empty(self, name: str) -> bool:
        """Whether an empty successful result should be returned to the model for rephrasing."""
        tool = self._tools.get(name)
        return bool(tool and tool.retry_on_empty)

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self._tools.get(call.name)
        observation_id = call.fingerprint[:16]
        if tool is None:
            return ToolResult(False, error="unknown_tool", observation_id=observation_id)
        if tool.capability not in context.capabilities:
            return ToolResult(False, error="capability_denied", observation_id=observation_id)
        supplied = set(call.arguments)
        required_values_are_valid = all(
            self._valid_argument(
                call.arguments[name], tool.argument_types.get(name, "string"), required=True,
            )
            for name in tool.required_argument_names
            if name in call.arguments
        )
        values_match_schema = all(
            self._valid_argument(value, tool.argument_types.get(name, "string"))
            for name, value in call.arguments.items()
        )
        if (
            not supplied.issubset(tool.argument_names)
            or not tool.required_argument_names.issubset(supplied)
            or not required_values_are_valid
            or not values_match_schema
        ):
            return ToolResult(False, error="invalid_arguments", observation_id=observation_id)
        try:
            async with asyncio.timeout(context.timeout_seconds):
                data = await tool.handler(dict(call.arguments), context)
        except TimeoutError:
            return ToolResult(False, error="tool_timeout", observation_id=observation_id)
        except (ValueError, LookupError) as exc:
            return ToolResult(False, error=str(exc), observation_id=observation_id)
        return ToolResult(True, data=self._truncate(data, tool.max_output_chars), observation_id=observation_id)

    @staticmethod
    def _valid_argument(value: Any, kind: str, *, required: bool = False) -> bool:
        if kind == "string":
            return isinstance(value, str) and (not required or bool(value.strip()))
        if kind == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if kind == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        return isinstance(value, bool)

    @staticmethod
    def _truncate(data: Any, limit: int) -> Any:
        if isinstance(data, str):
            return data[:limit]
        rendered = json.dumps(data, ensure_ascii=False, default=str)
        return data if len(rendered) <= limit else rendered[:limit]
