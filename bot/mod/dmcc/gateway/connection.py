"""bot/mod/dmcc/gateway/connection.py

bot/mod/dmcc/dmcc/gateway/connection.py

Modification():

- 封裝一個 TCP Minecraft Bridge 連線的 Protocol 與寫入狀態。
"""

from __future__ import annotations

import asyncio
import time

from ..protocol.codec import FrameDecoder, encode_frame
from ..protocol.models import Envelope


# ── Connection State ──────────────────────


class Connection:
    """一個尚未或已完成認證的 Bridge TCP 連線。"""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        max_frame_bytes: int,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.decoder = FrameDecoder(max_frame_bytes=max_frame_bytes)
        self.server_id: str | None = None
        self.challenge: str | None = None
        self.authenticated = False
        self.last_seen = time.monotonic()
        self._write_lock = asyncio.Lock()
        self._closed = False

    async def send(self, envelope: Envelope) -> None:
        """序列化後寫入一個完整 Frame，避免並發寫入交錯。"""

        if self._closed:
            raise ConnectionError("connection is closed")
        async with self._write_lock:
            self.writer.write(encode_frame(envelope))
            await self.writer.drain()

    async def close(self) -> None:
        """關閉底層 Stream；可安全重複呼叫。"""

        if self._closed:
            return
        self._closed = True
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, asyncio.IncompleteReadError):
            return
