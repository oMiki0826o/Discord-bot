"""
bot/mod/mc_backup/repositories/health.py

Modification():

- 以 atomic JSON 持久化排程備份健康與告警冷卻狀態。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .json_file import AtomicJsonFile


class JsonScheduleHealthRepository:
    def __init__(self, path: Path) -> None:
        self._file = AtomicJsonFile(path)

    def all(self) -> dict[str, dict[str, Any]]:
        return self._file.read(lambda: {}, self._deserialize)

    def set(self, server_id: str, value: dict[str, Any]) -> None:
        items = self.all()
        items[server_id] = value
        self._file.write({"servers": items})

    @staticmethod
    def _deserialize(value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict) or not isinstance(value.get("servers"), dict):
            raise ValueError("schedule health document must have servers")
        return {str(key): dict(item) for key, item in value["servers"].items() if isinstance(item, dict)}


def encode_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def decode_datetime(value: Any) -> datetime | None:
    return None if value in (None, "") else datetime.fromisoformat(str(value))
