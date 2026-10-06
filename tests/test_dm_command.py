"""
tests/test_dm_command.py

Modification():

- Discord-adapter behavior tests for the DM bridge Module.
- 維護 test dm command 的發布版行為與驗證契約。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.config import OWNER_ID
from bot.mod.dm.command import DMCog
from bot.mod.dm.config import DMSettings
from bot.mod.dm.service import DMBridgeService


class User:
    def __init__(self, user_id: int, *, bot: bool = False, fail_send: bool = False) -> None:
        self.id = user_id
        self.bot = bot
        self.fail_send = fail_send
        self.sent: list[tuple[str, tuple[object, ...]]] = []
        self.mention = f"<@{user_id}>"

    async def send(self, content: str, *args: object, **kwargs: object):
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append((content, tuple(kwargs.get("files", ()))))
        return SimpleNamespace(id=9000 + len(self.sent))


class Bot:
    def __init__(self, owner: User) -> None:
        self.owner = owner
        self.user = User(999, bot=True)
        self.users = {owner.id: owner}

    async def is_owner(self, user: User) -> bool:
        return user.id == self.owner.id

    async def application_info(self):
        return SimpleNamespace(owner=self.owner, team=None)

    def get_user(self, user_id: int):
        return self.users.get(user_id)

    async def fetch_user(self, user_id: int):
        return self.users[user_id]


class Context:
    def __init__(self, author: User) -> None:
        self.author = author
        self.sent: list[str] = []
        self.message = SimpleNamespace(attachments=())

    async def send(self, content: str) -> None:
        self.sent.append(content)


def bridge(bot: Bot) -> DMCog:
    settings = DMSettings(recent_senders_limit=2, forward_map_limit=2, owner_reply_prefix="Owner: ")
    return DMCog(bot, DMBridgeService(settings))


def configured_owner() -> User:
    """Use the same configured owner identity as the production resolver."""

    return User(OWNER_ID or 1)


def test_user_dm_forwards_to_owner_and_attachment_urls() -> None:
    async def scenario() -> None:
        owner = configured_owner()
        bot = Bot(owner)
        cog = bridge(bot)
        sender = User(2)
        message = SimpleNamespace(author=sender, guild=None, content="hello", mentions=(), attachments=(SimpleNamespace(url="https://cdn.example/file.txt"),))
        await cog.on_message(message)
        assert "hello" in owner.sent[0][0]
        assert owner.sent[1][0] == "Attachment: https://cdn.example/file.txt"
        assert cog.bridge.last_sender_id == "2"
        assert cog.bridge.sender_for_forward("9001") == "2"

    asyncio.run(scenario())


def test_bot_mention_dm_is_not_forwarded() -> None:
    async def scenario() -> None:
        owner = configured_owner()
        bot = Bot(owner)
        cog = bridge(bot)
        message = SimpleNamespace(author=User(2), guild=None, content="<@999> hi", mentions=(bot.user,), attachments=())
        await cog.on_message(message)
        assert owner.sent == []
        assert cog.bridge.last_sender_id is None

    asyncio.run(scenario())


def test_only_owner_reply_to_forward_is_bridged() -> None:
    async def scenario() -> None:
        owner = configured_owner()
        sender = User(2)
        bot = Bot(owner)
        bot.users[sender.id] = sender
        cog = bridge(bot)
        cog.bridge.remember_forward("50", "2")
        reply = SimpleNamespace(author=owner, guild=None, content="answer", attachments=(), reference=SimpleNamespace(message_id=50))
        assert await cog.handle_owner_reply(reply) is True
        assert sender.sent == [("Owner: answer", ())]
        stranger_reply = SimpleNamespace(author=User(3), guild=None, content="bad", attachments=(), reference=SimpleNamespace(message_id=50))
        assert await cog.handle_owner_reply(stranger_reply) is False
        assert sender.sent == [("Owner: answer", ())]

    asyncio.run(scenario())


def test_failed_forward_keeps_recent_sender() -> None:
    async def scenario() -> None:
        owner = User(OWNER_ID or 1, fail_send=True)
        bot = Bot(owner)
        cog = bridge(bot)
        message = SimpleNamespace(author=User(2), guild=None, content="hello", mentions=(), attachments=())
        await cog.on_message(message)
        assert cog.bridge.last_sender_id == "2"

    asyncio.run(scenario())


def test_dm_reply_uses_recent_sender() -> None:
    async def scenario() -> None:
        owner = configured_owner()
        sender = User(2)
        bot = Bot(owner)
        bot.users[sender.id] = sender
        cog = bridge(bot)
        cog.bridge.remember_sender("2")
        ctx = Context(owner)
        await cog.dm_reply.callback(cog, ctx, content="hello")
        assert sender.sent == [("Owner: hello", ())]
        assert ctx.sent == ["DM sent to <@2>."]

    asyncio.run(scenario())
