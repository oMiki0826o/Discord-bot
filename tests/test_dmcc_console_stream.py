"""tests/test_dmcc_console_stream.py

Modification():

- Require bounded authenticated console-log polling with redaction and no replay loop.
"""
from __future__ import annotations

import asyncio

import pytest

from bot.mod.dmcc.services.console_stream import (
    ConsoleStreamConfig,
    ConsoleStreamService,
    redact_console_line,
)


def _settings(**extra):
    return ConsoleStreamConfig.from_mapping({
        "enabled": True,
        "poll_seconds": 2,
        "servers": {"survival": {"channel_id": "123456789012345678"}},
        **extra,
    }, {"survival"})


def test_log_redaction_blocks_secrets_ips_and_mass_mentions() -> None:
    log = "Connected from 192.168.1.12 token=SUPER_SECRET_PASSWORD @everyone"
    redacted = redact_console_line(log)
    assert "192.168.1.12" not in redacted
    assert "SUPER_SECRET_PASSWORD" not in redacted
    assert "@everyone" not in redacted
    assert "[REDACTED]" in redacted


def test_stream_only_sends_new_lines_and_bounds_length() -> None:
    class Bridge:
        log_text = "boot\nready\n"
        async def log(self, server):
            return {"content": self.log_text}

    class Sender:
        messages = []
        async def send_discord_message(self, channel, content):
            self.messages.append((channel, content))

    class Manager:
        def get(self, server):
            return object()

    async def scenario():
        bridge = Bridge()
        sender = Sender()
        service = ConsoleStreamService(_settings(), bridge, Manager(), sender)
        await service.run_once()
        assert not sender.messages  # avoid replaying old history to a newly enabled channel
        bridge.log_text += "Player Steve from 10.20.30.40\n[Server] @here hello\n"
        await service.run_once()
        assert len(sender.messages) == 1
        assert "Steve" in sender.messages[0][1]
        assert "10.20.30.40" not in sender.messages[0][1]
        assert "@here" not in sender.messages[0][1]
        await service.run_once()
        assert len(sender.messages) == 1
        bridge.log_text += "X" * 30_000 + "\n"
        await service.run_once()
        assert len(sender.messages[-1][1]) <= 1900
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("settings", [
    {"enabled": "true"},
    {"poll_seconds": 0},
    {"servers": {"unknown": {"channel_id": "123456789012345678"}}},
    {"servers": {"survival": {"channel_id": "invalid"}}},
])
def test_invalid_stream_config_rejected(settings):
    with pytest.raises(ValueError):
        ConsoleStreamConfig.from_mapping(settings, {"survival"})
