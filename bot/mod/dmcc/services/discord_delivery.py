"""bot/mod/dmcc/services/discord_delivery.py

Modification():

- Implement and verify Minecraft Bridge presentation and safe Discord routing.

Discord API boundary for DMCC event delivery.

Secrets never appear in messages or log entries. Webhook failure can
fall back to the ordinary Bot channel without interrupting the event router.
"""
from __future__ import annotations

import logging
from typing import Any

import discord

from .presentation import OutboundDiscordMessage

logger = logging.getLogger(__name__)


class DiscordDeliveryAdapter:
    def __init__(self, bot: Any) -> None:
        self._bot = bot

    async def send_discord_message(self, channel_id: str, content: str) -> None:
        try:
            channel = self._bot.get_channel(int(channel_id))
        except (ValueError, TypeError):
            return
        if channel is not None and hasattr(channel, "send"):
            await channel.send(content, allowed_mentions=discord.AllowedMentions.none())

    async def send_discord_payload(self, payload: OutboundDiscordMessage) -> None:
        if payload.mode != "webhook" or payload.webhook_url is None:
            await self.send_discord_message(payload.channel_id, payload.content)
            return
        try:
            webhook = discord.Webhook.from_url(payload.webhook_url, client=self._bot)
            await webhook.send(
                payload.content,
                username=payload.username,
                avatar_url=payload.avatar_url,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.HTTPException, ValueError) as exc:
            logger.warning(
                "DMCC webhook delivery failed for channel %s (%s), using Bot fallback",
                payload.channel_id,
                type(exc).__name__,
            )
            await self.send_discord_message(payload.channel_id, payload.content)
