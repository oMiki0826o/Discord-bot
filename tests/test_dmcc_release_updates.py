"""tests/test_dmcc_release_updates.py

Modification():

- Tests for opt-in GitHub release announcements (never auto-install).
"""
from __future__ import annotations

import asyncio

import pytest

from bot.mod.dmcc.services.release_updates import ReleaseCheckConfig, ReleaseUpdateService


CHANNEL = "123456789012345678"


def _config(**overrides):
    return ReleaseCheckConfig.from_mapping({
        "enabled": True, "channel_id": CHANNEL, "interval_seconds": 21600,
        **overrides,
    })


def test_opt_in_and_validated_channel():
    assert not ReleaseCheckConfig.from_mapping({}).enabled
    assert _config().channel_id == CHANNEL
    for entry in ({"enabled": "true"}, {"enabled": True},
                  {"enabled": True, "channel_id": "abc"},
                  {"enabled": True, "channel_id": CHANNEL, "interval_seconds": 1},
                  {"enabled": True, "channel_id": CHANNEL, "url": "https://bad.example"}):
        with pytest.raises(ValueError):
            ReleaseCheckConfig.from_mapping(entry)


def test_announces_only_newer_stable_release_and_dedupes():
    async def scenario():
        sent = []
        class Sender:
            async def send_discord_message(self, channel, text):
                sent.append((channel, text))

        async def fetch():
            return {
                "tag_name": "v0.3.1",
                "html_url": "https://github.com/oMiki0826o/Discord-bot/releases/tag/v0.3.1",
                "draft": False, "prerelease": False,
            }

        service = ReleaseUpdateService(_config(), Sender(), "0.3.0", fetch_latest=fetch)
        assert await service.run_once()
        assert len(sent) == 1
        assert sent[0][0] == CHANNEL and "v0.3.1" in sent[0][1]
        assert not await service.run_once()
        assert len(sent) == 1
        await service.close()

    asyncio.run(scenario())


def test_untrusted_or_non_newer_release_is_ignored():
    async def scenario():
        sent = []
        class Sender:
            async def send_discord_message(self, channel, text):
                sent.append(text)
        for result in (
            {"tag_name": "v0.3.0", "html_url": "https://github.com/oMiki0826o/Discord-bot/releases/tag/v0.3.0"},
            {"tag_name": "v0.2.99", "html_url": "https://github.com/oMiki0826o/Discord-bot/releases/tag/v0.2.99"},
            {"tag_name": "v0.4.0", "html_url": "https://evil.example/steal"},
            {"tag_name": "v0.4.0", "html_url": "https://github.com/oMiki0826o/Discord-bot/releases/tag/v0.4.0", "prerelease": True},
            {"tag_name": "v0.4.0-rc1", "html_url": "https://github.com/oMiki0826o/Discord-bot/releases/tag/v0.4.0-rc1"},
        ):
            async def fetch(result=result):
                return result
            service = ReleaseUpdateService(_config(), Sender(), "0.3.0", fetch_latest=fetch)
            assert not await service.run_once()
        assert sent == []
    asyncio.run(scenario())


def test_manual_check_works_without_enabling_periodic_announcements():
    async def scenario():
        class Sender:
            async def send_discord_message(self, *_args):
                raise AssertionError("manual check must not send public notifications")

        async def fetch():
            return {
                "tag_name": "v0.3.2",
                "html_url": "https://github.com/oMiki0826o/Discord-bot/releases/tag/v0.3.2",
                "draft": False, "prerelease": False,
            }

        service = ReleaseUpdateService(
            ReleaseCheckConfig.from_mapping({}), Sender(), "0.3.0", fetch_latest=fetch
        )
        result = await service.check_now()
        assert result == ("v0.3.2", "https://github.com/oMiki0826o/Discord-bot/releases/tag/v0.3.2")
        assert not await service.run_once()
        await service.close()

    asyncio.run(scenario())
