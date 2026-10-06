"""bot/mod/dmcc/services/requests.py

bot/mod/dmcc/dmcc/services/requests.py

Modification():

- 提供 DMCC Console 與 Autocomplete 共用的 request-response 協調器。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from ..protocol.models import Envelope


# ── Models ──────────────────────


PacketSender = Callable[[Envelope], Awaitable[None]]


@dataclass(slots=True)
class _PendingRequest:
    server_id: str
    future: asyncio.Future[dict[str, object]]


# ── Service ──────────────────────


class RequestService:
    """為遠端 Bridge 請求提供配對、逾時與連線中斷安全處理。"""

    def __init__(self, sender: PacketSender, *, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._sender = sender
        self._timeout_seconds = timeout_seconds
        self._pending: dict[str, _PendingRequest] = {}

    async def request(
        self,
        server_id: str,
        packet_type: str,
        data: Mapping[str, object],
    ) -> dict[str, object]:
        """傳送 Request，等待相同 request_id 的 Response。"""

        if not server_id or not packet_type:
            raise ValueError("server_id and packet_type must be non-empty")
        request_id = uuid.uuid4().hex
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _PendingRequest(server_id, future)
        try:
            await self._sender(Envelope(1, packet_type, server_id, request_id, dict(data)))
            return await asyncio.wait_for(future, timeout=self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"DMCC request timed out: {packet_type}") from exc
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, envelope: Envelope) -> bool:
        """將合法同 Server 回覆交給等待它的 Request；晚到回覆直接忽略。"""

        request_id = envelope.request_id
        if request_id is None:
            return False
        pending = self._pending.get(request_id)
        if pending is None:
            return True
        if pending.server_id != envelope.server_id:
            return False
        if not pending.future.done():
            pending.future.set_result(dict(envelope.data))
        return True

    def cancel_server(self, server_id: str) -> None:
        """Bridge 斷線時使該 Server 所有等待中請求立即失敗。"""

        for pending in tuple(self._pending.values()):
            if pending.server_id == server_id and not pending.future.done():
                pending.future.set_exception(ConnectionError(f"server disconnected: {server_id}"))

    def pending_request_ids(self) -> tuple[str, ...]:
        """提供診斷與測試用的未完成 Request 快照。"""

        return tuple(self._pending)
