#!/usr/bin/env python3
"""
tools/import_minecraft_commands.py

Modification():

- Import YuYue71/Minecraft_Commands into the local AI knowledge source tree.
- 維護 import minecraft commands 的發布版行為與驗證契約。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPOSITORY_URL = "https://github.com/YuYue71/Minecraft_Commands"
TEXT_SUFFIXES = frozenset({".md", ".json", ".mcfunction", ".py", ".mcmeta"})


def read_text(path: Path) -> str:
    """Read the repository's mixed UTF-8/UTF-16 text files losslessly."""

    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"unsupported text encoding: {path}")


def output_path(source: Path, root: Path, output: Path) -> Path:
    relative = source.relative_to(root)
    if source.suffix.casefold() == ".mcmeta":
        return output / relative.with_suffix(".mcmeta.json")
    return output / relative


def import_repository(source: Path, output: Path, *, revision: str) -> int:
    """Copy supported text sources as UTF-8 while preserving their layout."""

    source = source.resolve()
    output = output.resolve()
    if not (source / "README.md").is_file():
        raise ValueError("source must be the Minecraft_Commands repository root")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or ".git" in path.parts or path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        content = read_text(path)
        if not content.strip():
            continue
        destination = output_path(path, source, output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        copied += 1

    (output / "SOURCE.md").write_text(
        "# Minecraft Commands 資料來源\n\n"
        f"來源 repository：{REPOSITORY_URL}\n\n"
        f"匯入 revision：`{revision}`\n\n"
        "內容保留原始相對路徑，並由 UTF-8／UTF-16 統一轉為 UTF-8 供本機 AI 知識索引使用。"
        "原始 repository 未提供 LICENSE 檔；再次散布前應先取得作者授權。\n",
        encoding="utf-8",
    )
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="cloned Minecraft_Commands repository")
    parser.add_argument("--output", type=Path, default=Path("data/ai/knowledge/minecraft_commands"))
    parser.add_argument("--revision", default="unknown")
    args = parser.parse_args()
    print(f"imported={import_repository(args.source, args.output, revision=args.revision)} output={args.output}")


if __name__ == "__main__":
    main()
