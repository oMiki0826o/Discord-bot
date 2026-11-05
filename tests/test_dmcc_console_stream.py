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


def test_bearer_authorization_and_ipv6_are_redacted() -> None:
    rendered = redact_console_line("Authorization: Bearer hiddenToken123 player [2001:db8::1]")
    assert "hiddenToken123" not in rendered
    assert "2001:db8" not in rendered
    assert "[REDACTED]" in rendered


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


def test_console_stream_rotation_and_disconnect_do_not_replay_history() -> None:
    class Bridge:
        text = "old startup\n"
        async def log(self, server_id):
            return {"content": self.text}

    class Manager:
        connected = True
        def get(self, server_id):
            return object() if self.connected else None

    class Sender:
        def __init__(self):
            self.messages = []
        async def send_discord_message(self, channel, content):
            self.messages.append(content)

    async def run() -> None:
        bridge, manager, sender = Bridge(), Manager(), Sender()
        stream = ConsoleStreamService(_settings(), bridge, manager, sender)
        await stream.run_once()
        bridge.text += "first real line\n"
        await stream.run_once()
        assert len(sender.messages) == 1
        bridge.text = "new file startup after rotate\n"
        await stream.run_once()
        assert len(sender.messages) == 1
        bridge.text += "new live entry\n"
        await stream.run_once()
        assert len(sender.messages) == 2
        assert "new live entry" in sender.messages[1]
        manager.connected = False
        await stream.run_once()
        manager.connected = True
        bridge.text += "another startup\n"
        await stream.run_once()
        assert len(sender.messages) == 2
        await stream.close()

    asyncio.run(run())


def test_cursor_mode_survives_service_restart_without_replaying_old_lines(tmp_path) -> None:
    class Bridge:
        def __init__(self):
            self.text = "older history\n"
            self.file_id = "inode-a"
            self.calls = []

        async def log_chunk(self, server_id, offset, file_id):
            self.calls.append((offset, file_id))
            if offset == -1:
                return {"content": "", "file_id": self.file_id, "next_offset": len(self.text)}
            if file_id != self.file_id:
                return {"content": self.text, "file_id": self.file_id, "next_offset": len(self.text)}
            return {
                "content": self.text[offset:],
                "file_id": self.file_id,
                "next_offset": len(self.text),
            }

    class Sender:
        def __init__(self):
            self.messages = []
        async def send_discord_message(self, channel, content):
            self.messages.append((channel, content))

    class Manager:
        connected = True
        def get(self, server):
            return object() if self.connected else None

    async def scenario() -> None:
        bridge, sender, manager = Bridge(), Sender(), Manager()
        cursor_file = tmp_path / "cursors.json"
        first = ConsoleStreamService(
            _settings(), bridge, manager, sender, cursor_path=cursor_file
        )
        await first.run_once()
        assert not sender.messages
        bridge.text += "new event one\n"
        await first.run_once()
        assert len(sender.messages) == 1
        assert "new event one" in sender.messages[-1][1]
        await first.close()

        manager.connected = False
        bridge.text += "offline but recoverable\n"
        restarted = ConsoleStreamService(
            _settings(), bridge, manager, sender, cursor_path=cursor_file
        )
        await restarted.run_once()
        manager.connected = True
        await restarted.run_once()
        assert len(sender.messages) == 2
        assert "offline but recoverable" in sender.messages[-1][1]
        assert "older history" not in sender.messages[-1][1]
        await restarted.run_once()
        assert len(sender.messages) == 2
        await restarted.close()

    asyncio.run(scenario())


def test_cursor_mode_retries_failed_discord_delivery(tmp_path) -> None:
    class Bridge:
        text = "history\n"
        async def log_chunk(self, server_id, offset, file_id):
            if offset == -1:
                return {"content": "", "file_id": "inode-z", "next_offset": len(self.text)}
            return {
                "content": self.text[offset:], "file_id": "inode-z",
                "next_offset": len(self.text),
            }

    class Sender:
        failures = 1
        messages = []
        async def send_discord_message(self, channel, content):
            if self.failures:
                self.failures -= 1
                raise ConnectionError("not delivered")
            self.messages.append(content)

    class Manager:
        def get(self, server_id):
            return object()

    async def scenario() -> None:
        bridge, sender = Bridge(), Sender()
        service = ConsoleStreamService(
            _settings(), bridge, Manager(), sender,
            cursor_path=tmp_path / "cursors.json",
        )
        await service.run_once()
        bridge.text += "must retry\n"
        await service.run_once()
        assert sender.messages == []
        await service.run_once()
        assert len(sender.messages) == 1
        assert "must retry" in sender.messages[0]
        await service.close()

    asyncio.run(scenario())


def test_console_redacts_private_player_commands_without_exposing_arguments() -> None:
    samples = [
        "[Server thread/INFO]: Player issued server command: /msg Steve private information",
        "[Server thread/INFO]: Player issued server command: /tell Alex password-value",
        "[Server thread/INFO]: Player issued server command: /login secret123",
        "[Server thread/INFO]: Player issued server command: /register hidden456",
        "[Server thread/INFO]: Player issued server command: /dmcc link ABCDEF",
    ]
    for entry in samples:
        rendered = redact_console_line(entry)
        assert "private information" not in rendered
        assert "password-value" not in rendered
        assert "secret123" not in rendered
        assert "hidden456" not in rendered
        assert "ABCDEF" not in rendered
        assert "[REDACTED]" in rendered
