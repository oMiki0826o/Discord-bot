"""
bot/mod/ai/data.py

Modification():

- 建立 AI Module 首次啟動所需的可編輯 data/ai/ 目錄。
- 只複製缺少的模板，不覆蓋部署者既有 Prompt、人格或資料。
"""

from __future__ import annotations

import shutil
from pathlib import Path


DATA_DIRECTORIES = ("prompt", "users_memory", "auto_memory", "knowledge")


def initialize_data_dir(data_dir: Path, *, resource_dir: Path) -> Path:
    """建立並補齊 data/ai；回傳標準化的資料根目錄。"""

    root = Path(data_dir)
    resources = Path(resource_dir)
    prompt = root / "prompt"
    (prompt / "personas").mkdir(parents=True, exist_ok=True)
    for name in DATA_DIRECTORIES:
        (root / name).mkdir(parents=True, exist_ok=True)

    _copy_if_missing(resources / "prompt" / "system.txt", prompt / "system.txt")
    personas_source = resources / "prompt" / "personas"
    if personas_source.is_dir():
        for profile_source in sorted(personas_source.iterdir(), key=lambda path: path.name):
            if not profile_source.is_dir() or profile_source.name.startswith("."):
                continue
            files = tuple(profile_source / f"{name}.txt" for name in ("persona", "background"))
            if not all(path.is_file() for path in files):
                continue
            profile_target = prompt / "personas" / profile_source.name
            for source in files:
                _copy_if_missing(source, profile_target / source.name)
    active = prompt / "personas" / "active.txt"
    if not active.exists():
        active.write_text("default\n", encoding="utf-8")

    for name in DATA_DIRECTORIES:
        _copy_if_missing(
            resources / "templates" / name / "填寫說明.md",
            root / name / "填寫說明.md",
        )
    return root


def _copy_if_missing(source: Path, target: Path) -> None:
    if target.exists() or not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
