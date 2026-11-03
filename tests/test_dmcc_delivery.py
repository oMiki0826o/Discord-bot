"""tests/test_dmcc_delivery.py

Modification():

- Implement and verify Minecraft Bridge presentation and safe Discord routing.

Discord delivery adapter prevents pings and isolates Webhook failures."""
from __future__ import annotations

import asyncio

import discord

from bot.mod.dmcc.services.discord_delivery import DiscordDeliveryAdapter
from bot.mod.dmcc.services.presentation import OutboundDiscordMessage


class _Channel:
    def __init__(self) -> None:
        self.calls = []

    async def send(self, content: str, **kwargs):
        self.calls.append((content, kwargs))


class _Bot:
    def __init__(self) -> None:
        self.channel = _Channel()

    def get_channel(self, channel_id: int):
        return self.channel if channel_id == 111 else None


def test_bot_delivery_disables_pings() -> None:
    async def scenario() -> None:
        bot = _Bot()
        sender = DiscordDeliveryAdapter(bot)
        await sender.send_discord_message("111", "@everyone message")
        assert len(bot.channel.calls) == 1
        content, kwargs = bot.channel.calls[0]
        assert content == "@everyone message"
        assert kwargs["allowed_mentions"].everyone is False

    asyncio.run(scenario())


def test_webhook_sender_overrides_identity_without_pings(monkeypatch) -> None:
    class Webhook:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, content: str, **kwargs) -> None:
            self.sent.append((content, kwargs))

    async def scenario() -> None:
        bot = _Bot()
        webhook = Webhook()
        monkeypatch.setattr(discord.Webhook, "from_url", lambda url, *, client: webhook)
        payload = OutboundDiscordMessage(
            "111", "@everyone yap", "webhook", "[生存服] tinglove711",
            "https://mc-heads.net/avatar/123e4567-e89b-12d3-a456-426614174000/64",
            "https://discord.com/api/webhooks/123456789012345678/test_secret",
        )
        await DiscordDeliveryAdapter(bot).send_discord_payload(payload)
        assert not bot.channel.calls
        assert webhook.sent[0][1]["username"] == "[生存服] tinglove711"
        assert webhook.sent[0][1]["allowed_mentions"].everyone is False

    asyncio.run(scenario())


def test_webhook_failure_falls_back_to_bot_without_leaking_secret(monkeypatch, caplog) -> None:
    class Webhook:
        async def send(self, content: str, **kwargs):
            response = type("Response", (), {"status": 403, "reason": "Forbidden"})()
            raise discord.Forbidden(response, "forbidden")

    async def scenario() -> None:
        bot = _Bot()
        monkeypatch.setattr(discord.Webhook, "from_url", lambda url, *, client: Webhook())
        url = "https://discord.com/api/webhooks/123456789012345678/test_secret"
        await DiscordDeliveryAdapter(bot).send_discord_payload(
            OutboundDiscordMessage("111", "test", "webhook", webhook_url=url, fallback_content="[生存服] <Steve> test")
        )
        assert bot.channel.calls[0][0] == "[生存服] <Steve> test"
        assert url not in caplog.text

    asyncio.run(scenario())
