"""tools/fabric_real_gateway_smoke.py

Modification():

- Run authenticated integration against the actual Python Gateway and Fabric Bridge.
- Verify server_started, server_info_request, command_request and public-event routing.
- Keep the listener on localhost and use only isolated smoke-test secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings
from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.gateway.server import Gateway


async def run_real_gateway_probe(
    *, port: int, secret: str, output: Path,
    ready: asyncio.Event | None = None, timeout: float = 100,
) -> None:
    """Exercise a real asynchronous Gateway with the connected Java Bridge."""
    if not secret:
        raise ValueError("missing local smoke-test secret")
    settings = DmccSettings.from_mapping({
        **DEFAULT_SETTINGS,
        "gateway": {"host": "127.0.0.1", "port": port},
        "servers": [{
            "server_id": "survival",
            "bridge": {"enabled": True, "secret_env": "DMCC_REAL_SMOKE_SECRET"},
        }],
    }, environ={"DMCC_REAL_SMOKE_SECRET": secret})
    gateway = Gateway(settings)
    started = asyncio.Event()
    public_message = asyncio.Event()
    minecraft_version: str | None = None

    async def on_event(event: MinecraftEvent) -> None:
        nonlocal minecraft_version
        if event.type == "server_started":
            raw = event.data.get("minecraft_version")
            if isinstance(raw, str) and raw:
                minecraft_version = raw
                started.set()
        elif event.type == "server_broadcast":
            if "DMCC_GATEWAY_SMOKE" in str(event.data.get("message", "")):
                public_message.set()

    gateway.relay.subscribe(on_event)
    await gateway.start()
    if ready is not None:
        ready.set()
    try:
        async with asyncio.timeout(timeout):
            await started.wait()
            info = await gateway.requests.request(
                "survival", "server_info_request", {},
            )
            if not isinstance(info.get("online_players"), (int, float)):
                raise AssertionError("server_info_response missing player count")
            reply = await gateway.requests.request(
                "survival", "command_request",
                {"command": "say DMCC_GATEWAY_SMOKE", "op_level": 4},
            )
            if not isinstance(reply.get("result"), (int, float)):
                raise AssertionError("command_response missing result")
            await public_message.wait()
            result = {
                "authenticated": True,
                "minecraft_version": minecraft_version,
                "server_info_response": True,
                "command_acknowledged": True,
                "public_broadcast_observed": True,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps(result), encoding="utf-8")
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
    finally:
        await gateway.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Real Python Gateway ↔ Fabric smoke test")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    secret = os.environ.get("DMCC_SMOKE_SECRET")
    if not secret:
        parser.error("DMCC_SMOKE_SECRET must be defined")
    try:
        asyncio.run(run_real_gateway_probe(
            port=args.port, secret=secret, output=args.output, timeout=args.timeout,
        ))
    except (OSError, AssertionError, ValueError, TimeoutError) as failure:
        print(f"Real Gateway smoke failed: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
