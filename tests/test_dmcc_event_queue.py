"""tests/test_dmcc_event_queue.py

Modification():

- Verify nonblocking, bounded Minecraft-to-Discord event delivery.

"""
from __future__ import annotations

import asyncio

from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.event_queue import DiscordEventQueue


def test_gateway_handler_does_not_wait_for_discord_network() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        started = asyncio.Event()
        events = []

        class Sender:
            async def forward(self, event):
                started.set()
                await release.wait()
                events.append(event.type)

        queue = DiscordEventQueue(Sender(), capacity=2)
        queue.start()
        await queue.publish(MinecraftEvent("player_chat", "survival", {}))
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.wait_for(
            queue.publish(MinecraftEvent("player_join", "survival", {})),
            timeout=0.1,
        )
        await asyncio.wait_for(
            queue.publish(MinecraftEvent("player_quit", "survival", {})),
            timeout=0.1,
        )
        assert queue.depth == 2
        assert queue.dropped == 0
        assert await queue.publish(MinecraftEvent("server_stopping", "survival", {})) is False
        assert queue.dropped == 1
        release.set()
        await queue.close(timeout=1)
        assert events == ["player_chat", "player_join", "player_quit"]

    asyncio.run(scenario())


def test_discord_delivery_errors_do_not_stall_following_events(caplog) -> None:
    async def scenario() -> None:
        processed = []

        class Sender:
            async def forward(self, event):
                if event.type == "player_chat":
                    raise RuntimeError("Discord failed")
                processed.append(event.type)

        queue = DiscordEventQueue(Sender(), capacity=4)
        queue.start()
        await queue.publish(MinecraftEvent("player_chat", "survival", {}))
        await queue.publish(MinecraftEvent("player_join", "survival", {}))
        await queue.close(timeout=1)
        assert processed == ["player_join"]

    asyncio.run(scenario())
    assert "Discord failed" in caplog.text


def test_queue_shutdown_is_bounded_when_discord_never_replies() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        unblock = asyncio.Event()

        class Sender:
            async def forward(self, event):
                started.set()
                await unblock.wait()

        queue = DiscordEventQueue(Sender(), capacity=1)
        queue.start()
        await queue.publish(MinecraftEvent("player_chat", "survival", {}))
        await started.wait()
        await asyncio.wait_for(queue.close(timeout=0.01), timeout=1)
        assert queue.stopped is True
        assert await queue.publish(MinecraftEvent("player_join", "survival", {})) is False

    asyncio.run(scenario())
