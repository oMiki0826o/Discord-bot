"""
tests/test_release_v2_resilience.py

Modification():

- 提供 test release v2 resilience 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from bot.core.settings.manager import SettingsManager
from bot.mod.ai.attachments.service import AttachmentInput, AttachmentService, AttachmentSettings
from bot.mod.ai.background.worker import BackgroundMemoryWorker
from bot.mod.ai.config import AiSettings, DEFAULT_SETTINGS
from bot.mod.ai.routing import Router
from bot.mod.ai.runtime.models import RuntimeResult, RuntimeStopReason
from bot.mod.ai.service import AIRequest, AIService


def test_video_metadata_does_not_block_event_loop(monkeypatch) -> None:
    async def exercise() -> None:
        monkeypatch.setattr(AttachmentService, "_video_metadata", staticmethod(
            lambda suffix, data: (time.sleep(0.08), "video")[1],
        ))
        service = AttachmentService(AttachmentSettings(1, 1_000, 1_000, 1_000))
        task = asyncio.create_task(service.process((
            AttachmentInput("clip.mp4", "video/mp4", b"video", 5),
        )))
        started = time.perf_counter()
        await asyncio.sleep(0.01)
        assert time.perf_counter() - started < 0.06
        assert (await task)[0].text == "video"

    asyncio.run(exercise())


def test_worker_close_cancels_stuck_processor() -> None:
    @dataclass(frozen=True)
    class Job:
        job_id: str = "job"
        event_id: str = "event"

    class Jobs:
        claimed = False
        recovered = False
        def recover_processing(self, *, now): self.recovered = True
        def claim(self, *, limit, now):
            if self.claimed: return ()
            self.claimed = True
            return (Job(),)
        def next_available_at(self): return None
        def complete(self, *args, **kwargs): raise AssertionError
        def fail(self, *args, **kwargs): raise AssertionError
        def defer_quota(self, *args, **kwargs): raise AssertionError

    async def exercise() -> None:
        started = asyncio.Event()
        async def processor(event):
            del event
            started.set()
            await asyncio.Event().wait()
        jobs = Jobs()
        worker = BackgroundMemoryWorker(
            jobs=jobs, events=SimpleNamespace(get=lambda _: object()),
            processor=processor, batch_size=1, clock=lambda: 1,
        )
        worker.start()
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.wait_for(worker.close(), timeout=1)
        assert jobs.recovered

    asyncio.run(exercise())


def test_settings_persist_failure_does_not_mutate_bound_runtime_data(tmp_path, monkeypatch) -> None:
    manager = SettingsManager(tmp_path)
    bound = manager.register("music", {"volume": 50})
    monkeypatch.setattr(manager, "_save_data", lambda name, data: (_ for _ in ()).throw(RuntimeError("save failed")))

    with pytest.raises(RuntimeError, match="save failed"):
        manager.set("music.volume", 80)

    assert manager.get("music.volume") == 50
    assert bound["volume"] == 50


def test_settings_reload_preserves_bound_identity(tmp_path) -> None:
    manager = SettingsManager(tmp_path)
    bound = manager.register("music", {"volume": 50})
    (tmp_path / "music.json").write_text(json.dumps({"volume": 80}), encoding="utf-8")

    manager.reload_all()

    assert manager._settings["music"] is bound
    assert bound["volume"] == 80


def test_ai_response_survives_background_side_effect_failure() -> None:
    class Permit:
        released: list[bool] = []
        def release(self, *, success): self.released.append(success)
    class Guard:
        permit = Permit()
        async def acquire(self, user_id, *, prompt): return self.permit
        def clear(self): return None
    class Events:
        def __init__(self): self.items = []
        def append(self, event): self.items.append(event); return event
    class Planner:
        async def build(self, *args, **kwargs): return object()
    class Prompts:
        def load(self): return object()
    class Composer:
        def compose(self, **kwargs): return SimpleNamespace(system_instruction="system", context_blocks=())
    class Runtime:
        async def run(self, request):
            return RuntimeResult("answer", RuntimeStopReason.COMPLETED, 1, 0, 1, request.model_candidates[0])
    class Jobs:
        def enqueue(self, *args, **kwargs): raise RuntimeError("queue unavailable")

    async def exercise() -> None:
        events = Events()
        service = AIService(
            settings=AiSettings.from_mapping(DEFAULT_SETTINGS), events=events, context=object(),
            context_planner=Planner(), prompts=Prompts(), composer=Composer(), router=Router(),
            guard=Guard(), runtime=Runtime(), memory_jobs=Jobs(),
            interaction_recorder=lambda user_id: (_ for _ in ()).throw(RuntimeError("stats unavailable")),
        )
        response = await service.generate(AIRequest(
            request_id="request", user_id="user", channel_id="channel", conversation_id="conversation",
            message_id="message", prompt="hello", created_at=1,
        ))
        assert response.text == "answer"
        assert len(events.items) == 2

    asyncio.run(exercise())
