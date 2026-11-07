"""tests/test_fabric_real_gateway_smoke.py

Modification():

- Verify real Python Gateway integration probe with a protocol-compatible fake Java peer.
- Covers authenticated command requests, event delivery, and negative failure responses.
"""
from __future__ import annotations

import asyncio
import json
import socket
import struct

from bot.mod.dmcc.protocol.auth import create_response
from bot.mod.dmcc.protocol.codec import encode_frame, decode_frame
from bot.mod.dmcc.protocol.models import Envelope
from tools.fabric_real_gateway_smoke import run_real_gateway_probe


async def _send(writer, kind, data, request_id=None):
    writer.write(encode_frame(Envelope(1, kind, "survival", request_id, data)))
    await writer.drain()


async def _receive(reader):
    header = await asyncio.wait_for(reader.readexactly(4), timeout=3)
    size = struct.unpack(">I", header)[0]
    return decode_frame(await asyncio.wait_for(reader.readexactly(size), timeout=3))


def test_real_gateway_probe_requires_confirmed_command_and_public_event(tmp_path):
    async def scenario():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        ready = asyncio.Event()
        output = tmp_path / "real-gateway.json"
        task = asyncio.create_task(run_real_gateway_probe(
            port=port, secret="isolated-test-secret", output=output,
            ready=ready, timeout=8,
        ))
        await asyncio.wait_for(ready.wait(), timeout=3)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            await _send(writer, "handshake", {"bridge_version": "test"})
            challenge = await _receive(reader)
            assert challenge.type == "challenge"
            await _send(writer, "authenticate", {"response": create_response(
                challenge.data["challenge"], "isolated-test-secret",
            )})
            assert (await _receive(reader)).type == "login_success"
            await _send(writer, "server_started", {"minecraft_version": "1.21.8"})
            req = await _receive(reader)
            assert req.type == "server_info_request"
            assert req.request_id
            await _send(writer, "server_info_response", {
                "online_players": 0, "minecraft_version": "1.21.8",
            }, req.request_id)
            cmd = await _receive(reader)
            assert cmd.type == "command_request"
            assert cmd.data["command"] == "say DMCC_GATEWAY_SMOKE"
            await _send(writer, "server_broadcast", {
                "player_name": "Server", "message": "DMCC_GATEWAY_SMOKE",
            })
            await _send(writer, "command_response", {"result": 1, "output": "ok"}, cmd.request_id)
            await asyncio.wait_for(task, timeout=3)
            report = json.loads(output.read_text())
            assert report["authenticated"] is True
            assert report["command_acknowledged"] is True
            assert report["public_broadcast_observed"] is True
        finally:
            writer.close()
            await writer.wait_closed()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_real_gateway_probe_does_not_succeed_without_public_event(tmp_path):
    async def scenario():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        ready = asyncio.Event()
        output = tmp_path / "incomplete.json"
        task = asyncio.create_task(run_real_gateway_probe(
            port=port, secret="isolated-test-secret", output=output,
            ready=ready, timeout=0.5,
        ))
        await asyncio.wait_for(ready.wait(), timeout=3)
        with __import__("pytest").raises(TimeoutError):
            await task
        assert not output.exists()
    asyncio.run(scenario())
