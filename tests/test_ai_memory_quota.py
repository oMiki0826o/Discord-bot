"""
tests/test_ai_memory_quota.py

Modification():

- 提供 test ai memory quota 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

from bot.mod.ai.background.jobs import JobStatus, MemoryJobRepository
from bot.mod.ai.background.worker import BackgroundMemoryWorker
from bot.mod.ai.database import AiDatabase
from bot.mod.ai.errors import CandidatePayloadError
from bot.mod.ai.provider.errors import ProviderUnavailableError
from bot.mod.ai.history.models import EventRole, NewEvent
from bot.mod.ai.history.repository import EventRepository
from bot.mod.ai.memory.extractor import MemoryCandidateParser


def test_quota_deferral_uses_provider_retry_time_without_consuming_attempt(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    EventRepository(database).append(
        NewEvent("event", "user", "channel", None, "conversation", EventRole.USER, "message", 100)
    )
    jobs = MemoryJobRepository(database, max_attempts=2, retry_base_seconds=30, retry_max_seconds=300)
    job = jobs.enqueue("event", now=100)
    claimed = jobs.claim(limit=1, now=100)[0]

    deferred = jobs.defer_quota(claimed.job_id, retry_after_seconds=120, now=100)

    assert deferred.status is JobStatus.PENDING
    assert deferred.available_at == 220
    assert deferred.attempts == job.attempts


def test_invalid_memory_candidate_is_rejected_without_retrying(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    events = EventRepository(database)
    events.append(NewEvent("event", "user", "channel", None, "conversation", EventRole.USER, "message", 100))
    jobs = MemoryJobRepository(database, max_attempts=5, retry_base_seconds=30, retry_max_seconds=300)

    async def invalid_payload(_event) -> None:
        raise CandidatePayloadError("Candidate 0 內容格式錯誤：importance 必須介於 1 到 5")

    worker = BackgroundMemoryWorker(
        jobs=jobs, events=events, processor=invalid_payload, batch_size=1, clock=lambda: 100,
    )
    jobs.enqueue("event", now=100)

    assert __import__("asyncio").run(worker.run_once()) == 0
    job = jobs.claim(limit=1, now=101)

    assert job == ()
    with database.connect() as connection:
        row = connection.execute("SELECT status, attempts, last_error FROM memory_jobs").fetchone()
    assert row["status"] == JobStatus.FAILED
    assert row["attempts"] == 1
    assert "importance" in row["last_error"]


def test_temporary_provider_outage_retries_without_a_terminal_failure(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    events = EventRepository(database)
    events.append(NewEvent("event", "user", "channel", None, "conversation", EventRole.USER, "message", 100))
    jobs = MemoryJobRepository(database, max_attempts=5, retry_base_seconds=30, retry_max_seconds=300)

    async def unavailable(_event) -> None:
        raise ProviderUnavailableError("503 UNAVAILABLE")

    worker = BackgroundMemoryWorker(
        jobs=jobs, events=events, processor=unavailable, batch_size=1, clock=lambda: 100,
    )
    jobs.enqueue("event", now=100)

    __import__("asyncio").run(worker.run_once())
    with database.connect() as connection:
        row = connection.execute("SELECT status, attempts, available_at, last_error FROM memory_jobs").fetchone()
    assert row["status"] == JobStatus.PENDING
    assert row["attempts"] == 1
    assert row["available_at"] == 130
    assert row["last_error"] == "503 UNAVAILABLE"


def test_memory_parser_normalizes_safe_importance_values() -> None:
    event = __import__("bot.mod.ai.history.models", fromlist=["StoredEvent"]).StoredEvent(
        "event", "user", "channel", None, "conversation", EventRole.USER, "message", 100, {},
    )
    payload = [{
        "type": "preference", "key": "language", "value": "zh-TW", "confidence": 0.9,
        "importance": "3", "assertion_strength": "explicit", "temporal_scope": "permanent",
    }]

    parsed = MemoryCandidateParser().parse(event, payload)

    assert parsed[0].importance == 3
