"""
bot/mod/agent/skills/service.py
Read editable SKILL.md files with strict paths, sizes and encoding.

Modification():
- Strengthen AI/Agent correctness and compatibility.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_SKILL_BYTES = 131_072


@dataclass(frozen=True, slots=True)
class SkillSummary:
    name: str
    summary: str
    when_to_use: str


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    name: str
    content: str


class SkillService:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _validated_path(self, name: str) -> Path:
        if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
            raise ValueError("Invalid skill name")
        folder = self.root / name
        file = folder / "SKILL.md"
        if folder.is_symlink() or file.is_symlink():
            raise ValueError("Skill symlinks are not permitted")
        if not file.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Invalid skill path")
        if not file.is_file():
            raise LookupError(f"Unknown skill: {name}")
        if file.stat().st_size > MAX_SKILL_BYTES:
            raise ValueError("Skill exceeds size limit")
        return file

    def list_skills(self) -> tuple[SkillSummary, ...]:
        if not self.root.is_dir():
            return ()
        summaries: list[SkillSummary] = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or folder.is_symlink() or not _SAFE_NAME.fullmatch(folder.name):
                continue
            try:
                path = self._validated_path(folder.name)
                metadata, _ = self._parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError, LookupError):
                continue
            if metadata.get("name", folder.name) != folder.name:
                continue
            summaries.append(SkillSummary(
                folder.name,
                metadata.get("summary", metadata.get("description", ""))[:500],
                metadata.get("when_to_use", "")[:500],
            ))
        return tuple(summaries)

    def read_skill(self, name: str) -> LoadedSkill:
        path = self._validated_path(name)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("Skill cannot be read") from exc
        return LoadedSkill(name, content)

    @staticmethod
    def _parse(content: str) -> tuple[dict[str, str], str]:
        if not content.startswith("---\n") or "\n---\n" not in content[4:]:
            return {}, content
        header, body = content[4:].split("\n---\n", 1)
        metadata: dict[str, str] = {}
        for line in header.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()
        return metadata, body
