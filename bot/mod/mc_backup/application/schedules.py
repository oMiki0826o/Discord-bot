"""bot/mod/mc_backup/application/schedules.py

Independent, cancellable backup schedule workers.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain.models import BackupSchedule, ManagedBackupServer
from ..repositories.schedules import JsonScheduleRepository


class BackupScheduleService:
    def __init__(
        self,
        servers: Mapping[str, ManagedBackupServer],
        coordinator: object,
        repository: JsonScheduleRepository,
    ) -> None:
        self._servers = dict(servers)
        self._coordinator = coordinator
        self._repository = repository
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    @property
    def active_server_ids(self) -> set[str]:
        return set(self._tasks)

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
            except Exception:
                continue

    def _start_worker(self, schedule: BackupSchedule) -> None:
        if schedule.server_id not in self._servers or schedule.server_id in self._tasks:
            return
        self._validate_schedule(schedule)
        self._tasks[schedule.server_id] = asyncio.create_task(
            self._worker(schedule), name=f"mc-backup-schedule:{schedule.server_id}"
        )

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
