"""
bot/mod/ai/prompt/loader.py

Modification():

- 以 runtime override 優先、module resource fallback 載入 Prompt Sources。
- 只在三份 source 全數成功時原子替換 last-known-good cache。
"""

from __future__ import annotations

import os
import json
import re
import tempfile
import shutil
from pathlib import Path

from ..errors import PromptSourceError
from .models import PromptSources


class PromptSourceLoader:
    _NAMES = ("system", "persona", "background")
    _PERSONA_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

    def __init__(
        self,
        *,
        resource_dir: Path,
        override_dir: Path,
    ) -> None:
        self.resource_dir = Path(resource_dir)
        self.override_dir = Path(override_dir)
        self._cached: PromptSources | None = None

    def load(self) -> PromptSources:
        if self._cached is None:
            self._cached = self._read_generation()
        return self._cached

    def reload(self) -> PromptSources:
        try:
            generation = self._read_generation()
        except PromptSourceError:
            if self._cached is None:
                raise
            return self._cached
        self._cached = generation
        return generation

    def install(self, sources: PromptSources) -> None:
        """Atomically publish sources already validated from a sync snapshot."""

        if not isinstance(sources, PromptSources):
            raise TypeError("sources must be PromptSources")
        self._cached = sources

    def list_personas(self) -> tuple[str, ...]:
        root = self.override_dir / "personas"
        if not root.is_dir():
            return ()
        return tuple(
            path.name
            for path in sorted(root.iterdir(), key=lambda item: item.name)
            if path.is_dir() and self._PERSONA_NAME.fullmatch(path.name)
        )

    def active_persona(self) -> str:
        path = self.override_dir / "personas" / "active.txt"
        value = path.read_text(encoding="utf-8").strip() if path.is_file() else "default"
        if self._PERSONA_NAME.fullmatch(value) is None:
            raise PromptSourceError("active persona name is invalid")
        return value

    def set_active_persona(self, name: str) -> str:
        if self._PERSONA_NAME.fullmatch(name) is None:
            raise ValueError("persona name is invalid")
        if name not in self.list_personas():
            raise LookupError(f"unknown persona: {name}")
        self._read_profile(name)
        active_path = self.override_dir / "personas" / "active.txt"
        previous = self.active_persona()
        active_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._atomic_write(active_path, name + "\n")
            self._cached = self._read_generation()
        except Exception:
            self._atomic_write(active_path, previous + "\n")
            raise
        return name

    def save_persona(self, name: str, persona: str, background: str) -> str:
        """Create or replace a complete editable persona profile atomically per file."""

        if self._PERSONA_NAME.fullmatch(name) is None:
            raise ValueError("persona name is invalid")
        persona_text = persona.strip()
        background_text = background.strip()
        if not persona_text or not background_text:
            raise ValueError("persona and background must not be blank")
        if len(persona_text) > 30_000 or len(background_text) > 30_000:
            raise ValueError("persona profile exceeds content limit")
        directory = self.override_dir / "personas" / name
        self._atomic_write(directory / "persona.txt", persona_text + "\n")
        self._atomic_write(directory / "background.txt", background_text + "\n")
        self._cached = self._read_generation()
        return name

    def delete_persona(self, name: str) -> bool:
        """Delete a non-default owner profile and safely fall back to default if active."""

        if name == "default":
            raise ValueError("default persona cannot be deleted")
        if self._PERSONA_NAME.fullmatch(name) is None:
            raise ValueError("persona name is invalid")
        directory = self.override_dir / "personas" / name
        if not directory.is_dir():
            return False
        if self.active_persona() == name:
            self._atomic_write(self.override_dir / "personas" / "active.txt", "default\n")
        shutil.rmtree(directory)
        self._cached = self._read_generation()
        return True

    def _read_generation(self) -> PromptSources:
        values = {
            name: self._read_source(name)
            for name in self._NAMES
        }
        values.update(
            moderation_rules=self._read_optional(self.override_dir / "moderation_rules.txt") or "",
            keywords=self._read_json_strings("keywords.json"),
            blocked_words=self._read_json_strings("blocked_words.json"),
            global_memory=self._read_json_strings("memory.json"),
            gemma_system=self._read_compact_source("gemma_system.txt"),
            gemma_persona=self._read_compact_source("gemma_persona.txt"),
            gemma_background=self._read_compact_source("gemma_background.txt"),
        )
        try:
            return PromptSources(**values)
        except ValueError as exc:
            raise PromptSourceError(str(exc)) from exc

    def _read_source(self, name: str) -> str:
        if name in {"persona", "background"}:
            profile = self.active_persona()
            override_path = self.override_dir / "personas" / profile / f"{name}.txt"
            fallback_path = self.resource_dir / "personas" / "default" / f"{name}.txt"
            legacy_fallback = self.resource_dir / f"{name}.txt"
        else:
            override_path = self.override_dir / f"{name}.txt"
            fallback_path = self.resource_dir / f"{name}.txt"
            legacy_fallback = None
        override = self._read_optional(override_path)
        if override is not None and override.strip():
            return override.strip()

        fallback = self._read_optional(fallback_path)
        if (fallback is None or not fallback.strip()) and legacy_fallback is not None:
            fallback = self._read_optional(legacy_fallback)
        if fallback is None or not fallback.strip():
            raise PromptSourceError(
                f"找不到有效的 {name}.txt prompt source"
            )
        return fallback.strip()

    def _read_profile(self, name: str) -> tuple[str, str]:
        values = tuple(self._read_optional(self.override_dir / "personas" / name / f"{item}.txt") for item in ("persona", "background"))
        if any(value is None or not value.strip() for value in values):
            raise PromptSourceError(f"persona profile is incomplete: {name}")
        return values[0].strip(), values[1].strip()

    def _read_compact_source(self, name: str) -> str:
        """Read an optional Gemma-specific source, preferring runtime overrides."""

        if name == "gemma_system.txt":
            override_path = self.override_dir / name
            fallback_path = self.resource_dir / name
        else:
            profile = self.active_persona()
            override_path = self.override_dir / "personas" / profile / name
            fallback_path = self.resource_dir / "personas" / "default" / name
        return (self._read_optional(override_path) or self._read_optional(fallback_path) or "").strip()

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    @staticmethod
    def _read_optional(path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise PromptSourceError(f"無法讀取 prompt source：{path.name}") from exc

    def _read_json_strings(self, name: str) -> tuple[str, ...]:
        """Read current list files and the legacy object-shaped prompt files."""
        path = self.override_dir / name
        content = self._read_optional(path)
        if content is None or not content.strip():
            return ()
        try:
            values = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PromptSourceError(f"prompt JSON 格式錯誤：{name}") from exc
        if isinstance(values, list):
            strings = values
        elif isinstance(values, dict):
            strings = self._legacy_strings(name, values)
        else:
            raise PromptSourceError(f"prompt JSON 必須是字串陣列或相容物件：{name}")
        if any(not isinstance(value, str) or not value.strip() for value in strings):
            raise PromptSourceError(f"prompt JSON 包含無效字串：{name}")
        return tuple(dict.fromkeys(value.strip() for value in strings))

    @staticmethod
    def _legacy_strings(name: str, values: dict[object, object]) -> list[object]:
        """Normalize the three object formats written by the legacy AI module."""

        if name == "memory.json":
            memories = values.get("memories", [])
            if not isinstance(memories, list):
                raise PromptSourceError("memory.json 的 memories 必須是陣列")
            result: list[object] = []
            for item in memories:
                result.append(item.get("content") if isinstance(item, dict) else item)
            return result

        result = []
        for value in values.values():
            if isinstance(value, list):
                result.extend(value)
        return result
