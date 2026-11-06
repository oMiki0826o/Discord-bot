"""tools/fabric_gateway_smoke.py

Modification():

- Validate a real Fabric Bridge over loopback TCP using Protocol v1 and HMAC.
- Check the server_started event and an actual Java server_info_response.
- No Discord credentials, remote network, or privileged command execution.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import threading


_MAX_FRAME = 262_144


def packet(kind: str, data: dict[str, object], request_id: str | None = None) -> bytes:
    payload = json.dumps(
        {"protocol_version": 1, "type": kind, "server_id": "survival",
         "request_id": request_id, "data": data},
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    if not payload or len(payload) > _MAX_FRAME:
        raise ValueError("invalid protocol frame size")
    return struct.pack(">I", len(payload)) + payload


def _receive(connection: socket.socket) -> dict[str, object]:
    header = _read_exact(connection, 4)
    length = struct.unpack(">I", header)[0]
    if length < 2 or length > _MAX_FRAME:
        raise ValueError("unsafe Protocol v1 frame size")
    value = json.loads(_read_exact(connection, length).decode("utf-8"))
    if not isinstance(value, dict) or value.get("protocol_version") != 1:
        raise ValueError("unexpected Protocol v1 envelope")
    if value.get("server_id") != "survival" or not isinstance(value.get("data"), dict):
        raise ValueError("unexpected server identity or data")
    return value


def _read_exact(connection: socket.socket, n: int) -> bytes:
    result = bytearray()
    while len(result) < n:
        chunk = connection.recv(n - len(result))
        if not chunk:
            raise EOFError("Fabric Bridge disconnected during protocol test")
        result.extend(chunk)
    return bytes(result)


def verify_fabric_bridge(
    *, port: int, secret: str, output: Path, ready: threading.Event | None = None,
    timeout: float = 100,
) -> None:
    """Accept one real Minecraft connection and require bidirectional traffic."""
    if not secret:
        raise ValueError("missing local test secret")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(1)
        listener.settimeout(timeout)
        if ready is not None:
            ready.set()
        print("DMCC loopback Gateway listening", flush=True)
        with listener.accept()[0] as peer:
            peer.settimeout(timeout)
            first = _receive(peer)
            if first.get("type") != "handshake":
                raise AssertionError("Fabric Bridge did not initiate a handshake")
            challenge = secrets.token_urlsafe(32)
            peer.sendall(packet("challenge", {"challenge": challenge}))
            auth = _receive(peer)
            expected = hmac.new(
                secret.encode(), challenge.encode(), hashlib.sha256,
            ).hexdigest()
            if auth.get("type") != "authenticate" or not hmac.compare_digest(
                str(auth["data"].get("response", "")), expected,
            ):
                raise AssertionError("Fabric Bridge did not authenticate")
            peer.sendall(packet("login_success", {}))
            started = None
            response = None
            command_ack = False
            public_broadcast = False
            while not (response is not None and command_ack and public_broadcast):
                incoming = _receive(peer)
                kind = incoming.get("type")
                if kind == "server_started" and started is None:
                    started = incoming
                    peer.sendall(packet("server_info_request", {}, "smoke-info-1"))
                elif kind == "server_info_response" and incoming.get("request_id") == "smoke-info-1":
                    response = incoming
                    peer.sendall(packet(
                        "command_request",
                        {"command": "say DMCC_GATEWAY_SMOKE", "op_level": 4},
                        "smoke-command-1",
                    ))
                elif kind == "command_response" and incoming.get("request_id") == "smoke-command-1":
                    data = incoming["data"]
                    if not isinstance(data.get("result"), (int, float)):
                        raise AssertionError("Java command response missing result")
                    command_ack = True
                elif kind == "server_broadcast":
                    data = incoming["data"]
                    if "DMCC_GATEWAY_SMOKE" in str(data.get("message", "")):
                        public_broadcast = True
                elif kind == "ping":
                    peer.sendall(packet("pong", incoming["data"], incoming.get("request_id")))
            if started is None or not isinstance(started["data"].get("minecraft_version"), str):
                raise AssertionError("Fabric server_started missing Minecraft version")
            if not isinstance(response["data"].get("online_players"), (int, float)):
                raise AssertionError("Java server_info_response missing player counts")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".tmp")
            temporary.write_text(json.dumps({
                "authenticated": True,
                "minecraft_version": started["data"]["minecraft_version"],
                "server_info_response": True,
                "command_acknowledged": command_ack,
                "public_broadcast_observed": public_broadcast,
            }), encoding="utf-8")
            temporary.replace(output)
            print("DMCC Fabric authentication, server info, command and event relay verified", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Fabric Bridge over localhost")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    secret = os.environ.get("DMCC_SMOKE_SECRET")
    if not secret:
        parser.error("DMCC_SMOKE_SECRET is required")
    try:
        verify_fabric_bridge(port=args.port, secret=secret, output=args.output)
    except (OSError, ValueError, AssertionError, EOFError) as failure:
        print(f"Fabric Gateway smoke failed: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
