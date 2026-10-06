"""
bot/mod/ai/config.py

Modification():

- 建立 AI Module 的中立預設值與型別化設定。
- 將 Gemini Secret 限定在 AI Module 邊界讀取。
- 提供可調整的 Knowledge Markdown chunk 大小。
- 將 Gemini 3+ 的 Agent web tool-combination 候選模型獨立為可設定 pool。

本檔案定義可發布的非機密 AI 設定契約。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

SETTINGS_NAME = "ai"

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_model": "gemini-3.1-flash-lite",
    "model_pools": {
        "chat": ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
        "vision": ["gemini-2.5-flash"],
        "web": [
            "gemini-2.5-flash",
            "gemini-3-flash-preview",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
        ],
        "agent_web": [
            "gemini-3-flash-preview",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
        ],
        "gemma": ["gemma-4-31b-it"],
        "background": ["gemini-3.1-flash-lite"],
    },
    "provider_timeout_seconds": 30.0,
    "provider_retries_per_model": 2,
    "quota_cooldown_seconds": 300,
    "max_output_tokens": 1200,
    "embedding_model": "gemini-embedding-001",
    "embedding_dimensions": 768,
    "knowledge_chunk_chars": 2_000,
    "cooldown_seconds": 3.0,
    "abuse_window_seconds": 60,
    "abuse_max_requests": 15,
    "max_prompt_chars": 20_000,
    "context_max_tokens": 4000,
    "recent_message_limit": 20,
    "prompt_log_channel_id": 0,
    "memory_jobs": {
        "batch_size": 10,
        "max_attempts": 5,
        "retry_base_seconds": 30,
        "retry_max_seconds": 1800,
    },
    "memory_mirror_poll_seconds": 2.0,
    "attachments": {
        "max_count": 5,
        "max_bytes_each": 10_000_000,
        "max_total_bytes": 25_000_000,
        "max_text_chars": 30_000,
    },
}


MODEL_SELECTOR_ORDER: tuple[tuple[str, str, str], ...] = (
    ("Gemini", "gemini", "chat"),
    ("Flash", "flash", "web"),
    ("Gemma", "gemma", "gemma"),
    ("Agent", "agent", "chat"),
)


def build_settings_schema(rule_type) -> dict[str, Any]:
    """Build the latest Core Settings schema without importing Core at package import time."""

    positive_int = lambda maximum: rule_type(int, minimum=1, maximum=maximum)
    positive_number = lambda maximum: rule_type((int, float), minimum=0.1, maximum=maximum)
    model_list = lambda values: bool(values) and all(isinstance(value, str) and bool(value.strip()) for value in values)
    return {
        "default_model": rule_type(str, validator=lambda value: bool(value.strip())),
        "model_pools.chat": rule_type(list, validator=model_list, description="must contain model names"),
        "model_pools.vision": rule_type(list, validator=model_list, description="must contain model names"),
        "model_pools.web": rule_type(list, validator=model_list, description="must contain model names"),
        "model_pools.agent_web": rule_type(list, validator=model_list, description="must contain Gemini 3+ model names"),
        "model_pools.gemma": rule_type(list, validator=model_list, description="must contain model names"),
        "model_pools.background": rule_type(list, validator=model_list, description="must contain model names"),
        "provider_timeout_seconds": positive_number(300),
        "provider_retries_per_model": positive_int(10),
        "quota_cooldown_seconds": positive_int(86_400),
        "max_output_tokens": positive_int(65_536),
        "embedding_model": rule_type(str, validator=lambda value: bool(value.strip())),
        "embedding_dimensions": positive_int(4_096),
        "knowledge_chunk_chars": rule_type(int, minimum=32, maximum=100_000),
        "cooldown_seconds": rule_type((int, float), minimum=0, maximum=3_600),
        "abuse_window_seconds": positive_int(86_400),
        "abuse_max_requests": positive_int(10_000),
        "max_prompt_chars": positive_int(1_000_000),
        "context_max_tokens": positive_int(1_000_000),
        "recent_message_limit": positive_int(1_000),
        "prompt_log_channel_id": rule_type(int, minimum=0, maximum=9_999_999_999_999_999_999),
        "memory_jobs.batch_size": positive_int(1_000),
        "memory_jobs.max_attempts": positive_int(100),
        "memory_jobs.retry_base_seconds": positive_int(86_400),
        "memory_jobs.retry_max_seconds": positive_int(604_800),
        "memory_mirror_poll_seconds": positive_number(300),
        "attachments.max_count": positive_int(100),
        "attachments.max_bytes_each": positive_int(1_000_000_000),
        "attachments.max_total_bytes": positive_int(2_000_000_000),
        "attachments.max_text_chars": positive_int(10_000_000),
    }


@dataclass(frozen=True, slots=True)
class AiSettings:
    default_model: str
    model_pools: Mapping[str, tuple[str, ...]]
    provider_timeout_seconds: float
    provider_retries_per_model: int
    quota_cooldown_seconds: int
    max_output_tokens: int
    embedding_model: str
    embedding_dimensions: int
    knowledge_chunk_chars: int
    cooldown_seconds: float
    abuse_window_seconds: int
    abuse_max_requests: int
    max_prompt_chars: int
    context_max_tokens: int
    recent_message_limit: int
    prompt_log_channel_id: int
    memory_jobs: Mapping[str, int]
    memory_mirror_poll_seconds: float
    attachments: Mapping[str, int]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "AiSettings":
        pools = {
            str(name): tuple(str(model).strip() for model in values if str(model).strip())
            for name, values in dict(raw["model_pools"]).items()
        }
        if not pools.get("chat"):
            raise ValueError("model_pools.chat 不得為空")
        default_model = str(raw["default_model"]).strip()
        if default_model not in pools["chat"]:
            raise ValueError("default_model 必須存在於 chat model pool")
        settings = cls(
            default_model=default_model,
            model_pools=MappingProxyType(pools),
            provider_timeout_seconds=float(raw["provider_timeout_seconds"]),
            provider_retries_per_model=int(raw["provider_retries_per_model"]),
            quota_cooldown_seconds=int(raw["quota_cooldown_seconds"]),
            max_output_tokens=int(raw["max_output_tokens"]),
            embedding_model=str(raw["embedding_model"]).strip(),
            embedding_dimensions=int(raw["embedding_dimensions"]),
            knowledge_chunk_chars=int(raw["knowledge_chunk_chars"]),
            cooldown_seconds=float(raw["cooldown_seconds"]),
            abuse_window_seconds=int(raw["abuse_window_seconds"]),
            abuse_max_requests=int(raw["abuse_max_requests"]),
            max_prompt_chars=int(raw["max_prompt_chars"]),
            context_max_tokens=int(raw["context_max_tokens"]),
            recent_message_limit=int(raw["recent_message_limit"]),
            prompt_log_channel_id=int(raw["prompt_log_channel_id"]),
            memory_jobs=MappingProxyType({k: int(v) for k, v in dict(raw["memory_jobs"]).items()}),
            memory_mirror_poll_seconds=float(raw["memory_mirror_poll_seconds"]),
            attachments=MappingProxyType({k: int(v) for k, v in dict(raw["attachments"]).items()}),
        )
        for name in (
            "provider_timeout_seconds", "provider_retries_per_model",
            "max_output_tokens", "abuse_window_seconds", "abuse_max_requests",
            "embedding_dimensions", "knowledge_chunk_chars", "max_prompt_chars", "context_max_tokens", "recent_message_limit",
            "memory_mirror_poll_seconds",
        ):
            if getattr(settings, name) <= 0:
                raise ValueError(f"{name} 必須大於 0")
        if settings.knowledge_chunk_chars < 32:
            raise ValueError("knowledge_chunk_chars 不得小於 32")
        if settings.cooldown_seconds < 0 or settings.quota_cooldown_seconds < 0:
            raise ValueError("cooldown seconds 不得小於 0")
        if settings.memory_jobs["retry_max_seconds"] < settings.memory_jobs["retry_base_seconds"]:
            raise ValueError("memory_jobs.retry_max_seconds 不得小於 retry_base_seconds")
        if settings.attachments["max_total_bytes"] < settings.attachments["max_bytes_each"]:
            raise ValueError("attachments.max_total_bytes 不得小於 max_bytes_each")
        if settings.attachments["max_count"] <= 0 or settings.attachments["max_text_chars"] <= 0:
            raise ValueError("attachment limits 必須大於 0")
        return settings


def model_selector_choices(settings: AiSettings) -> tuple[tuple[str, str], ...]:
    """Return slash-selector values that resolve to configured model pools."""

    return tuple(
        (label, selector)
        for label, selector, pool in MODEL_SELECTOR_ORDER
        if settings.model_pools.get(pool)
    )


def read_secret(environ: Mapping[str, str] | None = None) -> str:
    """讀取 AI Module 的 Gemini Secret，不讓 Core 理解供應商。"""

    source = os.environ if environ is None else environ
    return source.get("GEMINI_API", "").strip()
