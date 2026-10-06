"""bot/mod/mc_backup/repositories/history.py

Bounded human-readable operation history.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.models import OperationRecord
from .json_file import AtomicJsonFile


def _serialize(record: OperationRecord) -> dict[str, object]:
    return {
        "operation_id": record.operation_id,
        "server_id": record.server_id,
        "kind": record.kind,
        "success": record.success,
        "started_at": record.started_at.isoformat(),
        "finished_at": record.finished_at.isoformat(),
        "detail": record.detail,
    }


def _deserialize(value: Any) -> list[OperationRecord]:
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        raise ValueError("history document must have records")
    records: list[OperationRecord] = []
    for item in value["records"]:
        if not isinstance(item, dict):
            raise ValueError("history record must be an object")
        records.append(
            OperationRecord(
                operation_id=str(item["operation_id"]),
                server_id=str(item["server_id"]),
                kind=str(item["kind"]),
                success=bool(item["success"]),
                started_at=datetime.fromisoformat(str(item["started_at"])),
                finished_at=datetime.fromisoformat(str(item["finished_at"])),
                detail=str(item["detail"]),
            )
        )
    return records


class JsonHistoryRepository:
    def __init__(self, path: Path, *, max_records: int = 200) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self._file = AtomicJsonFile(path)
        self._max_records = max_records

    def append(self, record: OperationRecord) -> None:
        records = self._read()
        records.insert(0, record)
        self._file.write({"records": [_serialize(item) for item in records[: self._max_records]]})

    def recent(self) -> list[OperationRecord]:
        return self._read()

    def _read(self) -> list[OperationRecord]:
        return self._file.read(lambda: [], _deserialize)
