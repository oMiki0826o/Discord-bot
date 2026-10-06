"""bot/mod/dmcc/repositories/json_file.py
One validated atomic JSON file primitive for all DMCC repositories.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast


Document = TypeVar("Document")


class AtomicJsonFile:
    def __init__(
        self,
        path: Path,
        validator: Callable[[object], Document] | None = None,
    ) -> None:
        self._path = path
        self._validator = validator

    def read(self, default: Document) -> Document:
        if not self._path.exists():
            return default
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            if self._validator is not None:
                return self._validator(value)
            return cast(Document, value)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
            quarantine = self._quarantine()
            raise ValueError(f"invalid JSON document quarantined at {quarantine}") from exc

    def write(self, document: object) -> None:
        value = self._validator(document) if self._validator is not None else document
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self._path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _quarantine(self) -> Path:
        quarantine = self._path.with_suffix(f"{self._path.suffix}.corrupt")
        index = 1
        while quarantine.exists():
            quarantine = self._path.with_suffix(f"{self._path.suffix}.corrupt.{index}")
            index += 1
        os.replace(self._path, quarantine)
        return quarantine
