"""
tests/test_ai_memory_workflow.py

Modification():

- 驗證自動記憶從 durable job 到 SQLite 與 Owner JSON mirror 的完整流程。
"""

from __future__ import annotations

import asyncio
import json

from bot.mod.ai.background.extractor import ProviderMemoryExtractor
from bot.mod.ai.background.jobs import JobStatus, MemoryJobRepository
from bot.mod.ai.background.worker import BackgroundMemoryWorker
from bot.mod.ai.database import AiDatabase
from bot.mod.ai.history.models import EventRole, NewEvent
from bot.mod.ai.history.repository import EventRepository
from bot.mod.ai.memory.mirror import MemoryMirrorService
from bot.mod.ai.memory.repository import MemoryRepository
from bot.mod.ai.memory.service import MemoryService
from bot.mod.ai.provider.models import ProviderResponse


class _CandidateProvider:
    async def generate(self, request):
        del request
        return ProviderResponse(
            text=json.dumps([
                {
                    "type": "preference",
                    "key": "reply_language",
                    "value": "zh-TW",
                    "confidence": 0.9,
                    "importance": 4,
                    "assertion_strength": "explicit",
                    "temporal_scope": "permanent",
                },
            ]),
            model="test",
        )


def test_memory_worker_persists_an_accepted_candidate_and_exports_owner_mirror(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    events = EventRepository(database)
    event = events.append(NewEvent(
        "event", "123456789012345678", "channel", None, "conversation",
        EventRole.USER, "Please remember I prefer Traditional Chinese.", 100,
    ))
    memory = MemoryService(
        database=database,
        event_repository=events,
        memory_repository=MemoryRepository(database),
    )
    mirror = MemoryMirrorService(database, tmp_path / "auto_memory")
    extractor = ProviderMemoryExtractor(
        provider=_CandidateProvider(),
        memory_service=memory,
        model_candidates=("test",),
        mirror=mirror,
    )
    jobs = MemoryJobRepository(
        database,
        max_attempts=2,
        retry_base_seconds=30,
        retry_max_seconds=300,
    )
    worker = BackgroundMemoryWorker(
        jobs=jobs,
        events=events,
        processor=extractor,
        batch_size=1,
        clock=lambda: 100,
    )
    jobs.enqueue(event.event_id, now=100)

    assert asyncio.run(worker.run_once()) == 1

    with database.connect() as connection:
        assert connection.execute(
            "SELECT status FROM memory_jobs"
        ).fetchone()["status"] == JobStatus.COMPLETED.value
        row = connection.execute(
            "SELECT memory_key, value_json, status FROM memories"
        ).fetchone()
    assert dict(row) == {
        "memory_key": "reply_language",
        "value_json": '"zh-TW"',
        "status": "active",
    }
    output = next((tmp_path / "auto_memory").glob("*.json"))
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["user_id"] == event.user_id
    assert document["memories"][0]["memory_key"] == "reply_language"
