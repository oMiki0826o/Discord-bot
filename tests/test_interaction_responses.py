"""
tests/test_interaction_responses.py

Modification():

- 驗證 Slash Command 先確認 Discord Interaction。
- 驗證過期或已確認的 Interaction 不會產生第二次錯誤回覆。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from bot.core.discord.commands import send_interaction_error
from bot.mod.basic.help.command import HelpCog
from bot.mod.basic.ping import PingCog


def _interaction(*, response: object, followup: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        response=response,
        followup=followup or SimpleNamespace(send=AsyncMock()),
        user=SimpleNamespace(id=123),
        guild_id=None,
    )


def test_help_defers_before_building_command_pages() -> None:
    response = SimpleNamespace(defer=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    interaction = _interaction(response=response, followup=followup)
    bot = SimpleNamespace(tree=SimpleNamespace(get_commands=Mock(return_value=[])))

    asyncio.run(HelpCog.help.callback(HelpCog(bot), interaction))

    response.defer.assert_awaited_once_with(thinking=True)
    followup.send.assert_awaited_once_with("目前沒有可顯示的指令。", ephemeral=True)


def test_ping_defers_before_sending_latency() -> None:
    response = SimpleNamespace(defer=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    interaction = _interaction(response=response, followup=followup)
    bot = SimpleNamespace(latency=0.042)

    asyncio.run(PingCog.ping.callback(PingCog(bot), interaction))

    response.defer.assert_awaited_once_with(thinking=True)
    followup.send.assert_awaited_once_with("Ping：**42 ms**")


def test_expired_interaction_error_is_not_replied_twice(caplog: pytest.LogCaptureFixture) -> None:
    expired = discord.NotFound(
        SimpleNamespace(status=404, reason="Not Found"),
        {"code": 10062, "message": "Unknown interaction"},
    )
    response = SimpleNamespace(is_done=Mock(return_value=False), send_message=AsyncMock(side_effect=expired))

    with caplog.at_level("INFO"):
        asyncio.run(send_interaction_error(_interaction(response=response), "失敗"))

    assert "Interaction 已過期或已確認，略過錯誤回覆" in caplog.text
    assert "Interaction 錯誤訊息傳送失敗" not in caplog.text
