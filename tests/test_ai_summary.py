"""
tests/test_ai_summary.py

Modification():

- Conversation summaries remain derived, scoped Event data.
- 維護 test ai summary 的發布版行為與驗證契約。
"""

from __future__ import annotations

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.history.models import EventRole, NewEvent
from bot.mod.ai.history.repository import EventRepository
from bot.mod.ai.summary.repository import SummaryRepository
from bot.mod.ai.summary.service import SummaryService
from bot.mod.ai.background.extractor import ProviderMemoryExtractor
from bot.mod.ai.routing import extract_model_directive


def test_summary_is_current_only_for_matching_event_range_and_hash(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    repository = SummaryRepository(database)
    repository.save("conv-a", "user-a", "evt-1", "evt-2", "hash-a", "summary", now=10)

    assert repository.current("conv-a", "user-a", "evt-1", "evt-2", "hash-a").content == "summary"
    assert repository.current("conv-a", "user-a", "evt-1", "evt-2", "hash-b") is None


def test_summary_service_uses_event_range_hash(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    events = EventRepository(database)
    events.append(NewEvent("evt-1", "user-a", "channel", None, "conv-a", EventRole.USER, "first fact", 1))
    events.append(NewEvent("evt-2", "user-a", "channel", None, "conv-a", EventRole.ASSISTANT, "answer", 2))
    service = SummaryService(events, SummaryRepository(database))

    summary = service.save_text("user-a", "channel", "conv-a", "facts and decision", now=10)

    assert summary.first_event_id == "evt-1"
    assert service.current("user-a", "channel", "conv-a").content == "facts and decision"


def test_memory_extractor_ignores_non_array_json_response() -> None:
    assert ProviderMemoryExtractor._parse_json('{"memories": []}') == []


def test_memory_extractor_accepts_fenced_json_array() -> None:
    assert ProviderMemoryExtractor._parse_json("```json\n[]\n```") == []


def test_model_directive_is_case_insensitive_and_removed_from_prompt() -> None:
    assert extract_model_directive("使用 FLASH 分析這段程式") == ("flash", "分析這段程式")
    assert extract_model_directive("GEMINI: 查詢資料") == ("gemini", "查詢資料")
