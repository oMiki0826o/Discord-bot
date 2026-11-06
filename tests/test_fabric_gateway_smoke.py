"""tests/test_fabric_gateway_smoke.py

Modification():

- Check standalone Fabric Protocol v1 Gateway harness with a synthetic Java peer.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import socket
import struct
from threading import Event, Thread

from tools.fabric_gateway_smoke import packet, verify_fabric_bridge


def _read(sock):
    n = struct.unpack(">I", sock.recv(4))[0]
    data = bytearray()
    while len(data) < n:
        data.extend(sock.recv(n - len(data)))
    return json.loads(data.decode("utf-8"))


def test_live_fabric_gateway_probe_exchanges_hmac_and_server_info(tmp_path: Path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    ready = Event()
    errors = []
    output = tmp_path / "verified.json"

    def worker():
        try:
            verify_fabric_bridge(port=port, secret="test-secret", output=output, ready=ready, timeout=5)
        except Exception as exception:
            errors.append(exception)

    thread = Thread(target=worker, daemon=True)
    thread.start()
    assert ready.wait(3)
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.settimeout(3)
        sock.sendall(packet("handshake", {"bridge_version": "test"}))
        challenge = _read(sock)["data"]["challenge"]
        response = hmac.new(
            b"test-secret", challenge.encode(), hashlib.sha256,
        ).hexdigest()
        sock.sendall(packet("authenticate", {"response": response}))
        assert _read(sock)["type"] == "login_success"
        sock.sendall(packet("server_started", {"minecraft_version": "1.21.8"}))
        assert _read(sock)["type"] == "server_info_request"
        sock.sendall(packet("server_info_response", {"online_players": 0}, "smoke-info-1"))
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors
    assert json.loads(output.read_text()) == {
        "authenticated": True,
        "minecraft_version": "1.21.8",
        "server_info_response": True,
    }
