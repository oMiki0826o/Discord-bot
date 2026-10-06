"""
bot/mod/ai/memory/extractor.py

Modification():

- 將不可信任的 Provider Output 轉換成 Memory Candidate。
- 由程式注入 Event、User、Scope 與 Candidate Identity。
- 限制單一 Event 可產生的 Candidate 數量與欄位。
- 安全正規化模型輸出的整數 importance 表示法。

本檔不呼叫 Model Provider，也不修改 Memory。
"""

from __future__ import annotations

import json
import uuid

from ..errors import CandidatePayloadError
from ..history.models import EventRole, StoredEvent
from .models import (
    AssertionStrength,
    MemoryCandidate,
    MemoryScopeType,
    TemporalScope,
)


# ── Contract ──────────────────────

MAX_CANDIDATES_PER_EVENT = 8

_FIELDS = frozenset({
    "type",
    "key",
    "value",
    "confidence",
    "importance",
    "assertion_strength",
    "temporal_scope",
})


# ── Candidate Parser ──────────────────────

class MemoryCandidateParser:
    """驗證 Provider Output 並注入可信任的 Request Scope。"""

    def parse(
        self,
        event: StoredEvent,
        payload: object,
    ) -> tuple[MemoryCandidate, ...]:
        if event.role is not EventRole.USER:
            raise CandidatePayloadError(
                "Memory Candidate 只能來自 user event"
            )

        if not isinstance(payload, list):
            raise CandidatePayloadError(
                "Candidate Payload 根節點必須是 Array"
            )

        if len(payload) > MAX_CANDIDATES_PER_EVENT:
            raise CandidatePayloadError(
                f"單一 Event 最多產生 {MAX_CANDIDATES_PER_EVENT} 筆 Candidate"
            )

        candidates: list[MemoryCandidate] = []

        for index, raw_item in enumerate(payload):
            if not isinstance(raw_item, dict):
                raise CandidatePayloadError(
                    f"Candidate {index} 必須是 Object"
                )

            keys = set(raw_item)
            if keys != _FIELDS:
                missing = sorted(_FIELDS - keys)
                unknown = sorted(keys - _FIELDS)
                details = []
                if missing:
                    details.append("缺少欄位：" + ", ".join(missing))
                if unknown:
                    details.append("不允許欄位：" + ", ".join(unknown))
                raise CandidatePayloadError(
                    f"Candidate {index} 欄位錯誤（{'；'.join(details)}）"
                )

            try:
                normalized_item = dict(raw_item)
                normalized_item["importance"] = _normalize_importance(
                    normalized_item["importance"]
                )
                canonical = json.dumps(
                    normalized_item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                candidate_id = "candidate-" + uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{event.event_id}:{index}:{canonical}",
                ).hex

                candidate = MemoryCandidate(
                    candidate_id=candidate_id,
                    source_event_id=event.event_id,
                    user_id=event.user_id,
                    scope_type=MemoryScopeType.CHANNEL,
                    scope_id=event.channel_id,
                    memory_type=normalized_item["type"],
                    memory_key=normalized_item["key"],
                    value=normalized_item["value"],
                    confidence=normalized_item["confidence"],
                    importance=normalized_item["importance"],
                    assertion_strength=AssertionStrength(
                        normalized_item["assertion_strength"]
                    ),
                    temporal_scope=TemporalScope(
                        normalized_item["temporal_scope"]
                    ),
                    observed_at=event.created_at,
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise CandidatePayloadError(
                    f"Candidate {index} 內容格式錯誤：{exc}"
                ) from exc

            candidates.append(candidate)

        return tuple(candidates)


def _normalize_importance(value: object) -> object:
    """Accept lossless numeric representations while preserving range checks."""

    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
