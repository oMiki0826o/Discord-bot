"""
bot/mod/agent/tools/registry.py
Capability-scoped registry, validation, timeouts and structured truncation.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .models import Tool, ToolCall, ToolContext, ToolResult


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
            return ToolResult(False, error=type(exc).__name__.lower(), observation_id=observation_id)
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
        if len(rendered) <= limit:
            return data
        if limit < 38:
            return ""
        preview = rendered[:max(0, limit - 50)]
        result = {"truncated": True, "preview": preview}
        while len(json.dumps(result, ensure_ascii=False)) > limit and preview:
            preview = preview[:-1]
            result["preview"] = preview
        return result
