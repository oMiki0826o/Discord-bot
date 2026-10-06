"""bot/mod/mc_backup/repositories/json_file.py

Small atomic JSON document primitive with corrupt-file quarantine.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


class AtomicJsonFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self, default_factory: Callable[[], T], validate: Callable[[Any], T]) -> T:
        if not self.path.exists():
            return default_factory()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return validate(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            self._quarantine()
            return default_factory()

    def write(self, value: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                temporary.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _quarantine(self) -> None:
        index = 0
        while True:
            suffix = f".corrupt-{index}" if index else ".corrupt"
            target = self.path.with_name(f"{self.path.name}{suffix}")
            if not target.exists():
                os.replace(self.path, target)
                return
            index += 1
