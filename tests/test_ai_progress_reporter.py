"""
tests/test_ai_progress_reporter.py
Modification():
- Verify progress is factual, optional, throttled and replaced by the answer.
"""
from __future__ import annotations

import asyncio

from bot.mod.ai.commands.progress import ProgressReporter
from bot.mod.ai.runtime.events import ProgressEvent


def test_short_request_does_not_send_extra_status_message() -> None:
    async def run() -> None:
        sent = []
        async def send(text):
            sent.append(text)
            return object()
        async def edit(message, text):
            del message, text
        reporter = ProgressReporter(send, edit, delay_seconds=0.5)
        reporter.start()
        await reporter.publish(ProgressEvent("model.start", "正在產生回覆"))
        assert not await reporter.finish("你好")
        assert sent == []
    asyncio.run(run())


def test_slow_request_edits_one_message_then_replaces_with_answer() -> None:
    async def run() -> None:
        history = []
        message = object()
        async def send(text):
            history.append(("send", text))
            return message
        async def edit(ref, text):
            assert ref is message
            history.append(("edit", text))
        reporter = ProgressReporter(send, edit, delay_seconds=0, throttle_seconds=0)
        reporter.start()
        await asyncio.sleep(0.02)
        await reporter.publish(ProgressEvent("tool.start", "正在搜尋知識庫"))
        await reporter.publish(ProgressEvent("tool.complete", "搜尋知識庫完成"))
        assert await reporter.finish("最終答案\n\n-# Gemini · 輸入 10 / 輸出 5 tokens")
        assert history[0][0] == "send"
        assert "正在處理" in history[0][1]
        assert any("搜尋知識庫" in value for _, value in history)
        assert history[-1][1].startswith("最終答案")
    asyncio.run(run())
