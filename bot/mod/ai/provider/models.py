"""
bot/mod/ai/provider/models.py

Modification():

- 定義供應商中立的生成請求、策略與結果。
- 表達已驗證模型可使用的 built-in 與 function tool 組合。

本檔案是 Runtime 與實際 SDK adapter 之間的穩定契約。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    timeout_seconds: float = 30.0
    retries_per_model: int = 2
    allow_fallback: bool = True

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.retries_per_model < 1:
            raise ValueError("Provider timeout/retries 必須大於 0")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    request_id: str
    user_id: str
    prompt: str
    system_instruction: str
    model_candidates: tuple[str, ...]
    policy: ProviderPolicy = field(default_factory=ProviderPolicy)
    tools: tuple[dict[str, Any], ...] = ()
    transcript: tuple[dict[str, Any], ...] = ()
    binary_parts: tuple[BinaryPart, ...] = ()
    use_web: bool = False
    use_url_context: bool = False
    allow_combined_tools: bool = False
    max_output_tokens: int = 1200

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.user_id.strip() or not self.prompt.strip():
            raise ValueError("request_id/user_id/prompt 不得為空")
        if not self.model_candidates or any(not item.strip() for item in self.model_candidates):
            raise ValueError("model_candidates 不得為空")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens 必須大於 0")


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    name: str
    arguments: dict[str, Any]
    # Gemini thinking models require this opaque value to be returned with the
    # exact function-call part on the next tool turn.  It is deliberately
    # provider data, not an agent-visible instruction.
    thought_signature: Any = field(default=None, repr=False, compare=False)
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class BinaryPart:
    media_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    """Provider-reported evidence for optional web and URL tools."""

    grounded: bool = True
    url_context_succeeded: bool = True


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    model: str
    tool_calls: tuple[ProviderToolCall, ...] = ()
    raw: Any = field(default=None, repr=False, compare=False)
    model_content: Any = field(default=None, repr=False, compare=False)
    observation: ProviderObservation = field(default_factory=ProviderObservation)
