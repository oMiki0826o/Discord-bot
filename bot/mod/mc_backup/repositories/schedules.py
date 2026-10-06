"""bot/mod/mc_backup/repositories/schedules.py

Per-server JSON schedule persistence.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.models import BackupSchedule
from .json_file import AtomicJsonFile


def _deserialize(value: Any) -> dict[str, BackupSchedule]:
    if not isinstance(value, dict) or not isinstance(value.get("schedules"), dict):
        raise ValueError("schedule document must have schedules")
    result: dict[str, BackupSchedule] = {}
    for server_id, item in value["schedules"].items():
        if not isinstance(server_id, str) or not isinstance(item, dict):
            raise ValueError("invalid schedule entry")
        if type(item.get("enabled")) is not bool:
            raise ValueError("schedule enabled must be a boolean")
        result[server_id] = BackupSchedule(
            server_id=server_id,
            enabled=item["enabled"],
            time_of_day=str(item["time_of_day"]),
            timezone=str(item["timezone"]),
        )
    return result


class JsonScheduleRepository:
    def __init__(self, path: Path) -> None:
        self._file = AtomicJsonFile(path)

    def set(self, schedule: BackupSchedule) -> None:
        schedules = self.all()
        schedules[schedule.server_id] = schedule
        self._write(schedules)

    def get(self, server_id: str) -> BackupSchedule | None:
        return self.all().get(server_id)

    def all(self) -> dict[str, BackupSchedule]:
        return self._file.read(lambda: {}, _deserialize)

    def _write(self, schedules: dict[str, BackupSchedule]) -> None:
        self._file.write(
            {
                "schedules": {
                    server_id: {
                        "enabled": schedule.enabled,
                        "time_of_day": schedule.time_of_day,
                        "timezone": schedule.timezone,
                    }
                    for server_id, schedule in schedules.items()
                }
            }
        )
