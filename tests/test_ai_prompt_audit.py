"""
tests/test_ai_prompt_audit.py

Modification():

- 提供 test ai prompt audit 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

import asyncio

from bot.mod.ai.commands.discord import create_prompt_audit_sink
from bot.mod.ai.prompt.audit import redact_prompt


def test_prompt_audit_redacts_secrets_and_private_context() -> None:
    result = redact_prompt("token=abc\nAttachment note: private\nSystem: keep")
    assert "abc" not in result
    assert "private" not in result
    assert "System: keep" in result


def test_prompt_audit_sink_sends_only_redacted_content_to_configured_channel() -> None:
    class Channel:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send(self, content=None, **kwargs) -> None:
            del kwargs
            self.messages.append(str(content))

    class Bot:
        def __init__(self, channel) -> None:
            self.channel = channel

        def get_channel(self, channel_id):
            return self.channel if channel_id == 123 else None

    channel = Channel()
    sink = create_prompt_audit_sink(Bot(channel), 123)

    asyncio.run(sink("request", "user", "token=secret\nAttachment note: private\nSystem: keep"))

    assert len(channel.messages) == 1
    assert "secret" not in channel.messages[0]
    assert "private" not in channel.messages[0]
    assert "System: keep" in channel.messages[0]
