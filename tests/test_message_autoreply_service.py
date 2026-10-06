"""
tests/test_message_autoreply_service.py

Modification():

- 提供 test message autoreply service 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.mod.message.autoreply.matcher import AutoReplyMatcher
from bot.mod.message.autoreply.model import AutoReplyDocument, AutoReplyRule, MatchMode
from bot.mod.message.autoreply.repository import AutoReplyRepository
from bot.mod.message.autoreply.service import AutoReplyService


class FakeMessage:
    def __init__(self, *, bot: bool = False, webhook_id=None) -> None:
        self.guild = SimpleNamespace(id=1, name="測試服")
        self.channel = SimpleNamespace(id=2, mention="#聊天")
        self.author = SimpleNamespace(id=3, bot=bot, display_name="小明", mention="@小明")
        self.content = "hello"
        self.webhook_id = webhook_id
        self.replies = []

    async def reply(self, content, **kwargs):
        self.replies.append((content, kwargs))


def test_service_replies_once_with_mentions_disabled(tmp_path) -> None:
    repository = AutoReplyRepository(tmp_path)
    repository.save(
        1,
        AutoReplyDocument(
            1,
            1,
            (
                AutoReplyRule(
                    "hello", True, 1, MatchMode.EXACT, "hello", False,
                    "hi {username}", (), (), 0,
                ),
            ),
        ),
    )
    service = AutoReplyService(repository, AutoReplyMatcher(regex_timeout_seconds=0.05))
    message = FakeMessage()

    asyncio.run(service.handle_message(message))

    assert message.replies[0][0] == "hi 小明"
    assert message.replies[0][1]["mention_author"] is False
    assert message.replies[0][1]["allowed_mentions"].everyone is False


def test_service_ignores_bots_and_webhooks(tmp_path) -> None:
    service = AutoReplyService(
        AutoReplyRepository(tmp_path),
        AutoReplyMatcher(regex_timeout_seconds=0.05),
    )
    for bot, webhook in ((True, None), (False, 99)):
        message = FakeMessage(bot=bot, webhook_id=webhook)
        asyncio.run(service.handle_message(message))
        assert message.replies == []
