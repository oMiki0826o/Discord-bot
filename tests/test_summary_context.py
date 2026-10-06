"""
tests/test_summary_context.py

Modification():

- Context adds a valid summary only when raw history exceeds its budget.
- 維護 test summary context 的發布版行為與驗證契約。
"""

from __future__ import annotations

from bot.mod.ai.context.models import ContextRequest, ContextSource
from bot.mod.ai.context.service import ContextOrchestrator
from bot.mod.ai.database import AiDatabase
from bot.mod.ai.history.models import EventRole, NewEvent
from bot.mod.ai.history.repository import EventRepository
from bot.mod.ai.history.search import HistorySearchService


class _NoneService:
    def find_active(self, query): return ()
    def list(self, query): return ()


class _Summary:
    content = "compressed history"
    updated_at = 1


class _SummaryService:
    def current_for_events(self, events): return _Summary()


def test_context_uses_summary_when_recent_history_is_over_budget(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db"); database.initialize()
    events = EventRepository(database)
    events.append(NewEvent("old", "user", "channel", None, "conv", EventRole.USER, "x" * 400, 1))
    context = ContextOrchestrator(event_repository=events, history_search=HistorySearchService(database), memory_service=_NoneService(), topic_service=_NoneService(), summary_service=_SummaryService())

    pack = context.build(ContextRequest("user", "channel", "conv", "current", max_tokens=10, recent_limit=20, include_memory=False, include_topics=False))

    assert any(item.source is ContextSource.SUMMARY for item in pack.items)
