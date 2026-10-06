"""tests/test_dmcc_regressions.py

Modification():

- Covers release-critical DMCC protocol and provider boundary regressions.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from bot.mod.dmcc.protocol.codec import FrameDecoder, ProtocolError, encode_frame
from bot.mod.dmcc.protocol.models import Envelope
from bot.mod.dmcc.services.requests import RequestService


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
