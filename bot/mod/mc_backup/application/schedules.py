"""bot/mod/mc_backup/application/schedules.py

Independent, cancellable backup schedule workers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain.models import BackupSchedule, ManagedBackupServer
from ..repositories.schedules import JsonScheduleRepository
from ..repositories.health import JsonScheduleHealthRepository, decode_datetime, encode_datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScheduleHealth:
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None
    failure_fingerprint: str | None = None
    last_alert_at: datetime | None = None


class BackupScheduleService:
    def __init__(
        self,
        servers: Mapping[str, ManagedBackupServer],
        coordinator: object,
        repository: JsonScheduleRepository,
        health_repository: JsonScheduleHealthRepository | None = None,
        alert_sink: Callable[[str, ScheduleHealth], Awaitable[None]] | None = None,
        alert_cooldown_seconds: int = 21_600,
    ) -> None:
        self._servers = dict(servers)
        self._coordinator = coordinator
        self._repository = repository
        self._health_repository = health_repository
        self._alert_sink = alert_sink
        self._alert_cooldown_seconds = alert_cooldown_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._health = self._load_health()
        self._closed = False

    @property
    def active_server_ids(self) -> set[str]:
        return set(self._tasks)

    def health(self, server_id: str) -> ScheduleHealth:
        """Return the latest observable schedule result for one server."""

        return self._health.get(server_id, ScheduleHealth())

    async def start(self) -> None:
        self._closed = False
        for schedule in self._repository.all().values():
            if schedule.enabled:
                self._start_worker(schedule)

    async def close(self) -> None:
        self._closed = True
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def set_enabled(self, schedule: BackupSchedule) -> None:
        self._validate_schedule(schedule)
        self._repository.set(schedule)
        existing = self._tasks.pop(schedule.server_id, None)
        if existing is not None:
            existing.cancel()
            await asyncio.gather(existing, return_exceptions=True)
        if schedule.enabled and not self._closed:
            self._start_worker(schedule)

    async def run_due(self, server_ids: list[str]) -> None:
        for server_id in server_ids:
            server = self._servers.get(server_id)
            if server is None:
                continue
            try:
                await self._coordinator.create(server)  # type: ignore[attr-defined]
            except Exception as exc:
                previous = self.health(server_id)
                now = datetime.now(timezone.utc)
                fingerprint = f"{type(exc).__name__}:{str(exc)[:200]}"
                should_alert = (
                    self._alert_sink is not None
                    and (
                        previous.failure_fingerprint != fingerprint
                        or previous.last_alert_at is None
                        or (now - previous.last_alert_at).total_seconds() >= self._alert_cooldown_seconds
                    )
                )
                health = ScheduleHealth(
                    consecutive_failures=previous.consecutive_failures + 1,
                    last_success_at=previous.last_success_at,
                    last_failure_at=now,
                    last_error=f"{type(exc).__name__}: {str(exc)[:500]}",
                    failure_fingerprint=fingerprint,
                    last_alert_at=previous.last_alert_at,
                )
                self._set_health(server_id, health)
                logger.exception("Scheduled backup failed server_id=%s", server_id)
                if should_alert:
                    try:
                        await self._alert_sink(server_id, health)  # type: ignore[misc]
                    except Exception:
                        logger.exception("Scheduled backup alert failed server_id=%s", server_id)
                    else:
                        self._set_health(server_id, replace(health, last_alert_at=now))
                continue
            self._set_health(server_id, ScheduleHealth(
                last_success_at=datetime.now(timezone.utc),
            ))

    def _start_worker(self, schedule: BackupSchedule) -> None:
        if schedule.server_id not in self._servers or schedule.server_id in self._tasks:
            return
        self._validate_schedule(schedule)
        self._tasks[schedule.server_id] = asyncio.create_task(
            self._worker(schedule), name=f"mc-backup-schedule:{schedule.server_id}"
        )

    def _set_health(self, server_id: str, health: ScheduleHealth) -> None:
        self._health[server_id] = health
        if self._health_repository is not None:
            self._health_repository.set(server_id, {
                "consecutive_failures": health.consecutive_failures,
                "last_success_at": encode_datetime(health.last_success_at),
                "last_failure_at": encode_datetime(health.last_failure_at),
                "last_error": health.last_error,
                "failure_fingerprint": health.failure_fingerprint,
                "last_alert_at": encode_datetime(health.last_alert_at),
            })

    def _load_health(self) -> dict[str, ScheduleHealth]:
        if self._health_repository is None:
            return {}
        return {
            server_id: ScheduleHealth(
                consecutive_failures=int(item.get("consecutive_failures", 0)),
                last_success_at=decode_datetime(item.get("last_success_at")),
                last_failure_at=decode_datetime(item.get("last_failure_at")),
                last_error=None if item.get("last_error") is None else str(item["last_error"]),
                failure_fingerprint=None if item.get("failure_fingerprint") is None else str(item["failure_fingerprint"]),
                last_alert_at=decode_datetime(item.get("last_alert_at")),
            )
            for server_id, item in self._health_repository.all().items()
        }

    async def _worker(self, schedule: BackupSchedule) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self._seconds_until(schedule))
                if self._closed:
                    return
                await self.run_due([schedule.server_id])
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _validate_schedule(schedule: BackupSchedule) -> None:
        try:
            hour, minute = (int(value) for value in schedule.time_of_day.split(":", 1))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
            ZoneInfo(schedule.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("invalid backup schedule time or timezone") from exc

    @staticmethod
    def _seconds_until(schedule: BackupSchedule) -> float:
        zone = ZoneInfo(schedule.timezone)
        hour, minute = (int(value) for value in schedule.time_of_day.split(":", 1))
        now = datetime.now(zone)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())
