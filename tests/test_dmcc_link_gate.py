"""tests/test_dmcc_link_gate.py

Modification():

- Verify opt-in link state checks use authenticated Bridge requests and the existing link repository.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.repositories.links import JsonLinkRepository
from bot.mod.dmcc.services.linking import LinkingService
from bot.mod.dmcc.services.link_requests import LinkRequestHandler


def test_link_status_check_responds_for_linked_and_unlinked_players(tmp_path: Path) -> None:
    class Sender:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str, str | None, dict]] = []

        async def send_packet(self, server_id, packet_type, request_id, data) -> None:
            self.messages.append((server_id, packet_type, request_id, data))

    async def scenario() -> None:
        uuid = "123e4567-e89b-12d3-a456-426614174000"
        sender = Sender()
        store = JsonLinkRepository(tmp_path / "links.json")
        linking = LinkingService(link_store=store, code_factory=lambda: "ABCDEF")
        handler = LinkRequestHandler(linking, sender)
        event = MinecraftEvent("link_status_request", "survival", {
            "request_id": "request-one", "minecraft_uuid": uuid, "minecraft_name": "Steve",
        })
        await handler.handle(event)
        assert sender.messages[-1][:3] == ("survival", "link_status_response", "request-one")
        assert sender.messages[-1][3] == {"minecraft_uuid": uuid, "linked": False, "code": "ABCDEF"}
        linking.confirm_discord_link("ABCDEF", "234567890123456789")
        await handler.handle(MinecraftEvent("link_status_request", "survival", {
            "request_id": "request-two", "minecraft_uuid": uuid, "minecraft_name": "Steve",
        }))
        assert sender.messages[-1][3] == {"minecraft_uuid": uuid, "linked": True}
        assert sender.messages[-1][2] == "request-two"

    asyncio.run(scenario())


def test_link_status_check_ignores_invalid_identifiers(tmp_path: Path) -> None:
    class Sender:
        async def send_packet(self, *args) -> None:
            raise AssertionError("malformed status checks must never get a reply")

    async def scenario() -> None:
        handler = LinkRequestHandler(
            LinkingService(link_store=JsonLinkRepository(tmp_path / "links.json")), Sender()
        )
        for raw in ("not-uuid", "xyz", str(UUID(int=0))):
            await handler.handle(MinecraftEvent("link_status_request", "survival", {
                "request_id": "r", "minecraft_uuid": raw, "minecraft_name": "Steve",
            }))
    asyncio.run(scenario())


def test_unlinked_player_status_recheck_keeps_original_discord_code(tmp_path: Path) -> None:
    from datetime import datetime, UTC, timedelta

    now = [datetime(2026, 11, 5, tzinfo=UTC)]
    codes = iter(("ABCDEF", "GHJKLM"))
    store = JsonLinkRepository(tmp_path / "links.json")
    linking = LinkingService(
        link_store=store, code_factory=lambda: next(codes), now_provider=lambda: now[0]
    )
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert linking.begin_minecraft_link(uuid, "Steve") == "ABCDEF"
    now[0] += timedelta(seconds=30)
    assert linking.begin_minecraft_link(uuid, "Steve") == "ABCDEF"
    now[0] += timedelta(minutes=6)
    assert linking.begin_minecraft_link(uuid, "Steve") == "GHJKLM"
