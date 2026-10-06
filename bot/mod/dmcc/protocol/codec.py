"""bot/mod/dmcc/protocol/codec.py

bot/mod/dmcc/dmcc/protocol/codec.py

Modification():

- 實作 DMCC Protocol v1 的 UTF-8 JSON 與長度前綴 Frame 編解碼。
- 在解析前驗證 Frame 大小與 Envelope 結構，避免不可信連線耗盡資源。

本檔只處理 Protocol Wire Format，不處理連線、認證或 Minecraft 邏輯。
"""

from __future__ import annotations

import json
import struct

from .models import Envelope


# ── Errors ──────────────────────


class ProtocolError(ValueError):
    """A peer sent bytes that do not satisfy Protocol v1."""


_ENVELOPE_FIELDS = frozenset(
    {"protocol_version", "type", "server_id", "request_id", "data"}
)


# ── Envelope Validation ──────────────────────


def _validate_payload(value: object) -> Envelope:
    if not isinstance(value, dict) or set(value) != _ENVELOPE_FIELDS:
        raise ProtocolError("invalid Protocol v1 envelope fields")

    protocol_version = value["protocol_version"]
    message_type = value["type"]
    server_id = value["server_id"]
    request_id = value["request_id"]
    data = value["data"]

    if type(protocol_version) is not int or protocol_version != 1:
        raise ProtocolError("unsupported protocol_version")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("type must be a non-empty string")
    if not isinstance(server_id, str) or not server_id:
        raise ProtocolError("server_id must be a non-empty string")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id
    ):
        raise ProtocolError("request_id must be null or a non-empty string")
    if not isinstance(data, dict) or not all(
        isinstance(key, str) for key in data
    ):
        raise ProtocolError("data must be an object with string keys")

    return Envelope(
        protocol_version=protocol_version,
        type=message_type,
        server_id=server_id,
        request_id=request_id,
        data=data,
    )


# ── Single Frame Codec ──────────────────────


def decode_frame(frame: bytes, *, max_frame_bytes: int) -> Envelope:
    """Decode one payload after its four-byte frame length has been consumed."""

    if not isinstance(max_frame_bytes, int) or max_frame_bytes <= 0:
        raise ValueError("max_frame_bytes must be a positive integer")
    if len(frame) > max_frame_bytes:
        raise ProtocolError("frame exceeds configured limit")
    try:
        decoded = frame.decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("frame must be UTF-8 JSON") from exc
    return _validate_payload(value)


def encode_frame(envelope: Envelope) -> bytes:
    """Validate and encode an envelope as a network-order length-prefixed frame."""

    if not isinstance(envelope, Envelope):
        raise TypeError("envelope must be an Envelope")
    payload = {
        "protocol_version": envelope.protocol_version,
        "type": envelope.type,
        "server_id": envelope.server_id,
        "request_id": envelope.request_id,
        "data": dict(envelope.data),
    }
    _validate_payload(payload)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("envelope data is not JSON serializable") from exc
    if len(encoded) > 0xFFFFFFFF:
        raise ProtocolError("frame exceeds protocol maximum")
    return struct.pack(">I", len(encoded)) + encoded


# ── Stream Decoder ──────────────────────


class FrameDecoder:
    """Incrementally recover complete Protocol v1 envelopes from a byte stream."""

    def __init__(self, *, max_frame_bytes: int) -> None:
        if not isinstance(max_frame_bytes, int) or max_frame_bytes <= 0:
            raise ValueError("max_frame_bytes must be a positive integer")
        self._max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[Envelope]:
        if not isinstance(chunk, bytes):
            raise TypeError("chunk must be bytes")
        self._buffer.extend(chunk)
        decoded: list[Envelope] = []
        while len(self._buffer) >= 4:
            size = struct.unpack(">I", self._buffer[:4])[0]
            if size > self._max_frame_bytes:
                raise ProtocolError("declared frame exceeds configured limit")
            if len(self._buffer) < 4 + size:
                break
            payload = bytes(self._buffer[4 : 4 + size])
            del self._buffer[: 4 + size]
            decoded.append(
                decode_frame(payload, max_frame_bytes=self._max_frame_bytes)
            )
        return decoded
