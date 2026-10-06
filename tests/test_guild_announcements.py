"""
tests/test_guild_announcements.py

Modification():

- 提供 test guild announcements 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
from types import SimpleNamespace

from bot.mod.guild.announcement.model import Announcement, AnnouncementStatus
from bot.mod.guild.announcement.repository import AnnouncementRepository
from bot.mod.guild.announcement.scheduler import AnnouncementScheduler
from bot.mod.guild.announcement.service import AnnouncementService
from bot.mod.guild.database import GuildDatabase


UTC = timezone.utc


def draft(*, announcement_id: str = "a1", guild_id: int = 1) -> Announcement:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Announcement(
        id=announcement_id,
        guild_id=guild_id,
        author_id=2,
        target_channel_id=3,
        mention_role_id=0,
        title="公告",
        content="內容",
        color=0x5865F2,
        status=AnnouncementStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )


def test_announcement_repository_lifecycle_and_guild_isolation(tmp_path) -> None:
    repository = AnnouncementRepository(GuildDatabase(tmp_path / "guild.db"))
    value = draft()
    repository.create(value)
    assert repository.get(1, "a1") == value
    assert repository.get(2, "a1") is None

    when = datetime(2026, 1, 2, tzinfo=UTC)
    repository.schedule(1, "a1", when)
    assert repository.get(1, "a1").status is AnnouncementStatus.SCHEDULED
    assert repository.cancel(2, "a1") is False
    assert repository.cancel(1, "a1") is True
    assert repository.get(1, "a1").status is AnnouncementStatus.CANCELLED


def test_claim_due_is_atomic_and_stale_claim_can_recover(tmp_path) -> None:
    repository = AnnouncementRepository(GuildDatabase(tmp_path / "guild.db"))
    now = datetime(2026, 1, 2, tzinfo=UTC)
    repository.create(draft())
    repository.schedule(1, "a1", now - timedelta(seconds=1))

    first = repository.claim_due(now=now, stale_after=timedelta(minutes=5), limit=10)
    second = repository.claim_due(now=now, stale_after=timedelta(minutes=5), limit=10)
    recovered = repository.claim_due(now=now + timedelta(minutes=6), stale_after=timedelta(minutes=5), limit=10)

    assert [item.id for item in first] == ["a1"]
    assert second == ()
    assert [item.id for item in recovered] == ["a1"]


def test_publish_and_failure_results_are_persisted(tmp_path) -> None:
    repository = AnnouncementRepository(GuildDatabase(tmp_path / "guild.db"))
    now = datetime(2026, 1, 2, tzinfo=UTC)
    repository.create(draft())
    repository.schedule(1, "a1", now)
    repository.claim_due(now=now, stale_after=timedelta(minutes=5), limit=1)

    repository.mark_published(1, "a1", message_id=99, published_at=now)
    published = repository.get(1, "a1")
    assert published.status is AnnouncementStatus.PUBLISHED
    assert published.discord_message_id == 99

    repository.create(draft(announcement_id="a2"))
    repository.schedule(1, "a2", now)
    repository.claim_due(now=now, stale_after=timedelta(minutes=5), limit=1)
    repository.mark_failed(1, "a2", error="missing permission", retry_at=None)
    failed = repository.get(1, "a2")
    assert failed.status is AnnouncementStatus.FAILED
    assert failed.failure_count == 1


class FakeAnnouncementChannel:
    def __init__(self) -> None:
        self.id = 3
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(id=456)


def test_scheduler_publishes_due_announcement_once(tmp_path) -> None:
    repository = AnnouncementRepository(GuildDatabase(tmp_path / "guild.db"))
    now = datetime.now(UTC)
    repository.create(draft())
    repository.schedule(1, "a1", now - timedelta(seconds=1))
    channel = FakeAnnouncementChannel()
    guild = SimpleNamespace(
        id=1,
        get_channel=lambda channel_id: channel if channel_id == 3 else None,
        get_role=lambda _role_id: None,
    )
    bot = SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 1 else None)
    scheduler = AnnouncementScheduler(
        bot,
        repository,
        AnnouncementService(),
        poll_seconds=30,
        max_attempts=3,
    )

    report = asyncio.run(scheduler.run_once(now=now))
    second = asyncio.run(scheduler.run_once(now=now))

    assert report.published == 1
    assert second.published == 0
    assert len(channel.sent) == 1
    assert repository.get(1, "a1").discord_message_id == 456
