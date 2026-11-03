"""
bot/mod/ai/runtime/models.py

Modification():

- 定義基礎 AI 與可選 Runtime Extension 共用的請求與結果。

本檔不理解 Agent Tool 或供應商 SDK。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..provider.models import BinaryPart, TokenUsage


class RuntimeStopReason(StrEnum):
    COMPLETED = "completed"
    FORCED_FINALIZE = "forced_finalize"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    request_id: str
    user_id: str
    channel_id: str
    prompt: str
    guild_id: str = ""
    system_instruction: str = ""
    context_blocks: tuple[str, ...] = ()
    binary_parts: tuple[BinaryPart, ...] = ()
    model_candidates: tuple[str, ...] = ()
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.request_id, self.user_id, self.channel_id, self.prompt)):
            raise ValueError("runtime request identity and prompt must not be blank")
        if not self.model_candidates or any(not model.strip() for model in self.model_candidates):
            raise ValueError("runtime model candidates must not be empty")


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    text: str
    stop_reason: RuntimeStopReason
    model_turns: int
    tool_calls: int
    elapsed_ms: int
    model: str = ""
    observation_ids: tuple[str, ...] = ()
    read_only: bool = True
    usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("runtime result text must not be blank")
        if min(self.model_turns, self.tool_calls, self.elapsed_ms) < 0:
            raise ValueError("runtime counters must not be negative")
