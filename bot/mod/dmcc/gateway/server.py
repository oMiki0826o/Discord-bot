"""bot/mod/dmcc/gateway/server.py

bot/mod/dmcc/dmcc/gateway/server.py

Modification():

- 實作 DMCC Protocol v1 的 localhost TCP Gateway 與認證狀態機。
- 將已認證 Minecraft 事件交給 Relay Service，並提供反向純文字 Relay。

本檔不引用 Discord 或 Minecraft API。
"""

from __future__ import annotations

import asyncio

from ..config import DmccSettings
from ..events import MinecraftEvent
from ..protocol.auth import create_challenge, verify_response
from ..protocol.codec import ProtocolError
from ..protocol.models import Envelope
from ..services.relay import RelayService
from ..services.requests import RequestService
from .connection import Connection
from .manager import ConnectionManager


# ── Gateway ──────────────────────


class Gateway:
    """管理 Bridge TCP peers 與 Protocol v1 狀態轉換。"""

    def __init__(self, settings: DmccSettings) -> None:
        self._settings = settings
        self.manager = ConnectionManager()
        self.relay = RelayService()
        self.requests = RequestService(
            self._send_packet,
            timeout_seconds=settings.request_timeout_seconds,
        )
        self._server: asyncio.AbstractServer | None = None
        self._peers: set[Connection] = set()
        self._heartbeat_task: asyncio.Task[None] | None = None

    @property
    def address(self) -> tuple[str, int]:
        """回傳目前 Listener 的實際 localhost 位址。"""

        if self._server is None or not self._server.sockets:
            raise RuntimeError("gateway is not running")
        host, port = self._server.sockets[0].getsockname()[:2]
        return str(host), int(port)

    async def start(self) -> None:
        """開始接受 Bridge 連線；重複啟動屬於程式錯誤。"""

        if self._server is not None:
            raise RuntimeError("gateway is already running")
        self._server = await asyncio.start_server(
            self._handle_client,
            self._settings.host,
            self._settings.port,
        )
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="dmcc-heartbeat",
        )

    async def close(self) -> None:
        """停止 Listener 並關閉所有仍存在的 Peer。"""

        server, self._server = self._server, None
        heartbeat_task, self._heartbeat_task = self._heartbeat_task, None
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                heartbeat_task = None
        if server is not None:
            server.close()
            await server.wait_closed()
        peers = tuple(self._peers)
        await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
        self._peers.clear()

    async def _heartbeat_loop(self) -> None:
        """監看閒置 Peer，並對已認證 Bridge 維持 Protocol 層 liveness。"""

        try:
            while True:
                await asyncio.sleep(self._settings.heartbeat_interval_seconds)
                now = asyncio.get_running_loop().time()
                for connection in tuple(self._peers):
                    if now - connection.last_seen > self._settings.heartbeat_timeout_seconds:
                        await connection.close()
                        continue
                    if connection.authenticated and connection.server_id is not None:
                        try:
                            await connection.send(
                                Envelope(
                                    1,
                                    "ping",
                                    connection.server_id,
                                    None,
                                    {"timestamp": now},
                                )
                            )
                        except ConnectionError:
                            await connection.close()
        except asyncio.CancelledError:
            raise

    async def send_minecraft_message(self, server_id: str, message: str) -> None:
        """透過指定已認證 Bridge 顯示一則純文字 Minecraft 訊息。"""

        if not isinstance(message, str) or not message:
            raise ValueError("message must be a non-empty string")
        await self._send_packet(
            Envelope(
                protocol_version=1,
                type="minecraft_message",
                server_id=server_id,
                request_id=None,
                data={"message": message},
            )
        )

    async def send_packet(
        self,
        server_id: str,
        packet_type: str,
        request_id: str | None,
        data: dict[str, object],
    ) -> None:
        """Send a validated module-originated protocol packet to one Bridge."""

        if not isinstance(packet_type, str) or not packet_type:
            raise ValueError("packet_type must be non-empty")
        await self._send_packet(Envelope(1, packet_type, server_id, request_id, data))

    async def _send_packet(self, envelope: Envelope) -> None:
        """將已驗證 Protocol 封包傳給指定線上的 Bridge。"""

        connection = self.manager.get(envelope.server_id)
        if connection is None:
            raise LookupError(f"server is not connected: {envelope.server_id}")
        await connection.send(envelope)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        connection = Connection(
            reader,
            writer,
            max_frame_bytes=self._settings.frame_max_bytes,
        )
        self._peers.add(connection)
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                for envelope in connection.decoder.feed(chunk):
                    connection.last_seen = asyncio.get_running_loop().time()
                    await self._process(connection, envelope)
                    if not connection.authenticated and connection.server_id is None:
                        return
        except (ConnectionError, asyncio.IncompleteReadError, ProtocolError):
            return
        finally:
            self.manager.unregister(connection.server_id, connection)
            if connection.server_id is not None:
                self.requests.cancel_server(connection.server_id)
            self._peers.discard(connection)
            await connection.close()

    async def _process(self, connection: Connection, envelope: Envelope) -> None:
        if not connection.authenticated:
            await self._process_authentication(connection, envelope)
            return
        if envelope.server_id != connection.server_id:
            await connection.close()
            return
        if envelope.type == "ping":
            await connection.send(
                Envelope(1, "pong", envelope.server_id, envelope.request_id, envelope.data)
            )
            return
        if envelope.type == "pong":
            return
        if envelope.type in {
            "command_response",
            "autocomplete_response",
            "server_info_response",
            "log_response",
            "stats_response",
        }:
            if not self.requests.resolve(envelope):
                await connection.close()
            return
        if envelope.type in {
            "server_started", "server_stopping", "player_chat", "player_join", "player_quit", "player_death", "player_advancement", "player_gamemode", "link_request", "unlink_request",
        }:
            event_data = dict(envelope.data)
            if envelope.request_id is not None:
                event_data["request_id"] = envelope.request_id
            await self.relay.publish(
                MinecraftEvent(
                    type=envelope.type,
                    server_id=envelope.server_id,
                    data=event_data,
                )
            )
            return
        await connection.close()

    async def _process_authentication(
        self,
        connection: Connection,
        envelope: Envelope,
    ) -> None:
        if envelope.type == "handshake" and connection.server_id is None:
            if self._settings.server_secret(envelope.server_id) is None:
                await self._reject(connection, envelope.server_id, "server_not_allowed")
                return
            if self.manager.get(envelope.server_id) is not None:
                await self._reject(connection, envelope.server_id, "server_id_in_use")
                return
            connection.server_id = envelope.server_id
            connection.challenge = create_challenge()
            await connection.send(
                Envelope(
                    1,
                    "challenge",
                    envelope.server_id,
                    None,
                    {"challenge": connection.challenge},
                )
            )
            return
        if (
            envelope.type == "authenticate"
            and connection.server_id == envelope.server_id
            and connection.challenge is not None
        ):
            secret = self._settings.server_secret(envelope.server_id)
            response = envelope.data.get("response")
            if secret is not None and verify_response(
                connection.challenge,
                secret,
                response,
            ) and self.manager.register(envelope.server_id, connection):
                connection.authenticated = True
                connection.challenge = None
                await connection.send(
                    Envelope(1, "login_success", envelope.server_id, None, {})
                )
                return
            await self._reject(connection, envelope.server_id, "authentication_failed")
            return
        await connection.close()

    async def _reject(
        self,
        connection: Connection,
        server_id: str,
        reason: str,
    ) -> None:
        await connection.send(
            Envelope(1, "login_failure", server_id, None, {"reason": reason})
        )
        await connection.close()
