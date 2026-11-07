"""tests/test_dmcc_gateway_integration.py

Modification():

- Run an actual loopback Protocol v1 handshake and authenticated Minecraft event delivery.
- Keep this test independent of the public Discord network and Minecraft runtime.

"""
from __future__ import annotations

import asyncio
import socket
import struct

from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings
from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.gateway.server import Gateway
from bot.mod.dmcc.protocol.auth import create_response
from bot.mod.dmcc.protocol.codec import decode_frame, encode_frame
from bot.mod.dmcc.protocol.models import Envelope
from bot.mod.dmcc.repositories.state import JsonStateRepository
from bot.mod.dmcc.services.minecraft_discord_relay import MinecraftDiscordRelayService
from bot.mod.dmcc.services.presentation import PresentationSettings
from bot.mod.dmcc.services.event_queue import DiscordEventQueue


async def _send(writer, kind, data):
    writer.write(encode_frame(Envelope(1, kind, "survival", None, data)))
    await writer.drain()


async def _receive(reader):
    header = await asyncio.wait_for(reader.readexactly(4), timeout=2)
    length = struct.unpack(">I", header)[0]
    return decode_frame(await asyncio.wait_for(reader.readexactly(length), timeout=2), max_frame_bytes=262144)


def test_authenticated_bridge_chat_and_metrics_reach_correct_subscribers(tmp_path):
    async def scenario():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        settings = DmccSettings.from_mapping({
            **DEFAULT_SETTINGS, "gateway": {"host": "127.0.0.1", "port": port},
            "servers": [{"server_id": "survival", "bridge": {
                "enabled": True, "secret_env": "BRIDGE_TEST_SECRET",
            }}],
        }, environ={"BRIDGE_TEST_SECRET": "a-long-unique-local-integration-secret"})
        state = JsonStateRepository(tmp_path / "state.json")
        state.initialize()
        state.set_channel_mapping("survival", "123456789012345678")
        ready = asyncio.Event()
        received = []
        class Sender:
            async def send_discord_payload(self, payload):
                received.append(payload)
                ready.set()
        gateway = Gateway(settings)
        queue = DiscordEventQueue(MinecraftDiscordRelayService(
            state, Sender(), PresentationSettings.from_mapping({
                "servers": {"survival": {"label": "生存服"}},
            })
        ))
        metrics = []
        async def record(event: MinecraftEvent):
            if event.type == "server_metrics":
                metrics.append(event.data["mspt"])
        gateway.relay.subscribe(queue.publish)
        gateway.relay.subscribe(record)
        queue.start()
        await gateway.start()
        try:
            reader, writer = await asyncio.open_connection(*gateway.address)
            try:
                await _send(writer, "handshake", {})
                challenge = await _receive(reader)
                assert challenge.type == "challenge"
                await _send(writer, "authenticate", {
                    "response": create_response(
                        challenge.data["challenge"], "a-long-unique-local-integration-secret"
                    )
                })
                assert (await _receive(reader)).type == "login_success"
                await _send(writer, "player_chat", {
                    "player_name": "Steve", "message": "Hello from Minecraft",
                })
                await _send(writer, "server_metrics", {
                    "mspt": 42.0, "tps": 20.0, "online_players": 1, "max_players": 20,
                })
                await asyncio.wait_for(ready.wait(), timeout=2)
                assert received[0].channel_id == "123456789012345678"
                assert received[0].content == "[生存服] <Steve> Hello from Minecraft"
                # A separate telemetry subscription sees only authenticated packets.
                await asyncio.sleep(0)
                assert metrics == [42.0]
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await gateway.close()
            await queue.close()
    asyncio.run(scenario())


def test_unauthenticated_bridge_cannot_inject_minecraft_chat():
    async def scenario():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        settings = DmccSettings.from_mapping({
            **DEFAULT_SETTINGS, "gateway": {"host": "127.0.0.1", "port": port},
            "servers": [{"server_id": "survival", "bridge": {
                "enabled": True, "secret_env": "BRIDGE_TEST_SECRET",
            }}],
        }, environ={"BRIDGE_TEST_SECRET": "a-long-unique-local-integration-secret"})
        gateway = Gateway(settings)
        events = []
        async def record(event):
            events.append(event)
        gateway.relay.subscribe(record)
        await gateway.start()
        try:
            reader, writer = await asyncio.open_connection(*gateway.address)
            try:
                await _send(writer, "player_chat", {
                    "player_name": "Mallory", "message": "Unverified data",
                })
                assert await asyncio.wait_for(reader.read(), timeout=2) == b""
                assert events == []
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await gateway.close()
    asyncio.run(scenario())


def test_link_status_roundtrip_over_authenticated_gateway(tmp_path):
    from bot.mod.dmcc.repositories.links import JsonLinkRepository
    from bot.mod.dmcc.services.linking import LinkingService
    from bot.mod.dmcc.services.link_requests import LinkRequestHandler

    async def scenario():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        settings = DmccSettings.from_mapping({
            **DEFAULT_SETTINGS,
            "gateway": {"host": "127.0.0.1", "port": port},
            "servers": [{"server_id": "survival", "bridge": {
                "enabled": True, "secret_env": "BRIDGE_TEST_SECRET",
            }}],
        }, environ={"BRIDGE_TEST_SECRET": "a-long-unique-local-integration-secret"})
        gateway = Gateway(settings)
        store = JsonLinkRepository(tmp_path / "links.json")
        linking = LinkingService(link_store=store, code_factory=lambda: "ABCDEF")
        gateway.relay.subscribe(LinkRequestHandler(linking, gateway).handle)
        await gateway.start()
        try:
            reader, writer = await asyncio.open_connection(*gateway.address)
            try:
                await _send(writer, "handshake", {})
                challenge = await _receive(reader)
                await _send(writer, "authenticate", {
                    "response": create_response(
                        challenge.data["challenge"], "a-long-unique-local-integration-secret"
                    )
                })
                assert (await _receive(reader)).type == "login_success"
                uuid = "123e4567-e89b-12d3-a456-426614174000"
                writer.write(encode_frame(Envelope(1, "link_status_request", "survival", "status-1", {
                    "minecraft_uuid": uuid, "minecraft_name": "Steve",
                })))
                await writer.drain()
                response = await _receive(reader)
                assert response.type == "link_status_response"
                assert response.request_id == "status-1"
                assert response.data["linked"] is False
                assert response.data["code"] == "ABCDEF"
                linking.confirm_discord_link("ABCDEF", "234567890123456789")
                writer.write(encode_frame(Envelope(1, "link_status_request", "survival", "status-2", {
                    "minecraft_uuid": uuid, "minecraft_name": "Steve",
                })))
                await writer.drain()
                response = await _receive(reader)
                assert response.type == "link_status_response"
                assert response.request_id == "status-2"
                assert response.data == {"minecraft_uuid": uuid, "linked": True}
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await gateway.close()
    asyncio.run(scenario())


def test_authenticated_gateway_handles_bursts_and_reconnect_without_ghost_events():
    async def scenario():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        secret = "stress-fixture-secret"
        settings = DmccSettings.from_mapping({
            **DEFAULT_SETTINGS,
            "gateway": {"host": "127.0.0.1", "port": port},
            "servers": [{"server_id": "survival", "bridge": {
                "enabled": True, "secret_env": "BRIDGE_STRESS_SECRET",
            }}],
        }, environ={"BRIDGE_STRESS_SECRET": secret})
        gateway = Gateway(settings)
        received = []
        done = asyncio.Event()

        async def record(event):
            if event.type == "player_chat":
                received.append(str(event.data.get("message", "")))
                if len(received) >= 250:
                    done.set()

        gateway.relay.subscribe(record)
        await gateway.start()
        try:
            reader, writer = await asyncio.open_connection(*gateway.address)
            try:
                await _send(writer, "handshake", {})
                challenge = await _receive(reader)
                await _send(writer, "authenticate", {
                    "response": create_response(challenge.data["challenge"], secret),
                })
                assert (await _receive(reader)).type == "login_success"
                # A second connection using the same server ID must not hijack
                # the first authenticated peer.
                other_reader, other_writer = await asyncio.open_connection(*gateway.address)
                try:
                    await _send(other_writer, "handshake", {})
                    assert (await _receive(other_reader)).type == "login_failure"
                finally:
                    other_writer.close()
                    await other_writer.wait_closed()
                batch = b"".join(
                    encode_frame(Envelope(1, "player_chat", "survival", None, {
                        "player_name": "Steve", "message": f"message-{i}",
                    })) for i in range(250)
                )
                writer.write(batch)
                await writer.drain()
                await asyncio.wait_for(done.wait(), timeout=8)
                assert received == [f"message-{i}" for i in range(250)]
            finally:
                writer.close()
                await writer.wait_closed()
            for _ in range(100):
                if gateway.manager.get("survival") is None:
                    break
                await asyncio.sleep(0.01)
            assert gateway.manager.get("survival") is None
            # The next authenticated session is accepted after the first closes.
            reader, writer = await asyncio.open_connection(*gateway.address)
            try:
                await _send(writer, "handshake", {})
                challenge = await _receive(reader)
                assert challenge.type == "challenge"
                await _send(writer, "authenticate", {
                    "response": create_response(challenge.data["challenge"], secret),
                })
                assert (await _receive(reader)).type == "login_success"
                pending = asyncio.create_task(gateway.requests.request(
                    "survival", "server_info_request", {},
                ))
                assert (await _receive(reader)).type == "server_info_request"
                writer.close()
                await writer.wait_closed()
                with __import__("pytest").raises(ConnectionError):
                    await asyncio.wait_for(pending, timeout=3)
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await gateway.close()
    asyncio.run(scenario())
