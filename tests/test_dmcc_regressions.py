"""tests/test_dmcc_regressions.py

Modification():

- Covers release-critical DMCC protocol and provider boundary regressions.
"""

from __future__ import annotations

import asyncio
import copy
import struct
from pathlib import Path

import pytest

from bot.mod.dmcc.protocol.codec import FrameDecoder, ProtocolError, encode_frame
from bot.mod.dmcc.protocol.models import Envelope
from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings, SettingsError
from bot.mod.dmcc.domain.models import ProcessState
from bot.mod.dmcc.providers.control.local_tmux import LocalTmuxControlProvider
from bot.mod.dmcc.providers.control.mcsm import McsmControlProvider
from bot.mod.dmcc.services.requests import RequestService


def _settings(**updates):
    raw = copy.deepcopy(DEFAULT_SETTINGS)
    raw.update(updates)
    return raw


def test_outbound_frame_limit_is_enforced() -> None:
    envelope = Envelope(1, "test", "survival", None, {"text": "x" * 500})
    with pytest.raises(ProtocolError, match="configured limit"):
        encode_frame(envelope, max_frame_bytes=128)


def test_inbound_declared_frame_limit_is_enforced_before_payload() -> None:
    decoder = FrameDecoder(max_frame_bytes=128)
    with pytest.raises(ProtocolError, match="declared frame"):
        decoder.feed(struct.pack(">I", 129))


def test_late_response_after_timeout_is_ignored_without_protocol_failure() -> None:
    async def run() -> None:
        sent: list[Envelope] = []

        async def sender(envelope: Envelope) -> None:
            sent.append(envelope)

        service = RequestService(sender, timeout_seconds=0.001)
        with pytest.raises(TimeoutError):
            await service.request("survival", "console.request", {"command": "list"})
        assert len(sent) == 1
        assert service.pending_request_ids() == ()
        assert service.resolve(sent[0]) is True

    asyncio.run(run())


def test_dmcc_configuration_rejects_unsafe_gateway_and_boolean_values() -> None:
    with pytest.raises(SettingsError, match="127.0.0.1"):
        DmccSettings.from_mapping(_settings(gateway={"host": "0.0.0.0", "port": 8765}), environ={})
    with pytest.raises(SettingsError, match="identity_enabled"):
        DmccSettings.from_mapping(_settings(servers=[{"server_id": "survival", "identity_enabled": "false"}]), environ={})
    with pytest.raises(SettingsError, match="262144"):
        DmccSettings.from_mapping(_settings(frame_max_bytes=262_145), environ={})


def test_local_tmux_target_and_mcsm_contract(tmp_path: Path) -> None:
    raw = _settings(
        providers={"control": [{"provider_id": "local", "type": "local_tmux", "options": {"server_dir": str(tmp_path), "session_name": "minecraft", "start_argv": ["java", "-jar", "server.jar"]}}], "backup": []},
        servers=[{"server_id": "survival", "control_provider": "local", "control_target": "wrong"}],
    )
    with pytest.raises(SettingsError, match="control_target"):
        DmccSettings.from_mapping(raw, environ={})

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []
        async def request_json(self, method, path, *, params, payload):
            self.calls.append((method, path, params, payload))
            return {"status": 200, "data": {"status": 3}}

    async def run() -> None:
        client = FakeClient()
        provider = McsmControlProvider("panel", client, "daemon-1", "instance-1")
        assert await provider.status() is ProcessState.RUNNING
        await provider.start()
        assert [call[:2] for call in client.calls] == [("GET", "/api/instance"), ("GET", "/api/protected_instance/open")]

    asyncio.run(run())
