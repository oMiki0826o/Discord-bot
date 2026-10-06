"""
bot/mod/agent/provider_adapter.py

Modification():

- 將 AI public model-turn facade 轉換為 Agent Runtime 的 ModelTurn。
- 將 Gemini 原始 tool context 與 function call ID 保留給後續回合。

本檔不匯入 Gemini SDK 或 AI Provider 實作。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..ai.api import RuntimeRequest

from .runtime import ModelTurn
from .tools import ToolCall


class AiModelAdapter:
    def __init__(self, services: Any) -> None:
        self.services = services

    async def generate_turn(self, request: RuntimeRequest, transcript: Sequence[dict[str, Any]], declarations: tuple[dict[str, object], ...], *, allow_tools: bool) -> ModelTurn:
        response = await self.services.generate_model_turn(
            request,
            tuple(transcript),
            declarations,
            allow_tools=allow_tools,
        )
        calls = tuple(
            ToolCall(call.name, dict(call.arguments), call.thought_signature, call.call_id)
            for call in response.function_calls
        )
        return ModelTurn(response.text, calls, response.model, response.model_content)

    async def close(self) -> None:
        return None
