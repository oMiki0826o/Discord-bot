"""
tests/test_divination_importer.py

Modification():

- 驗證占卜知識庫匯入時保留 Markdown 並轉換 CSV／JSON。
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.import_divination import convert_directory


def test_convert_directory_writes_markdown_for_supported_knowledge_sources(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "knowledge"
    (source / "data").mkdir(parents=True)
    (source / "notes.md").write_text("# 原始筆記\n\n內容。\n", encoding="utf-8")
    (source / "data" / "cards.csv").write_text("\ufeffname,meaning\n太陽,成功\n", encoding="utf-8")
    (source / "data" / "metadata.json").write_text(
        json.dumps({"system": "tarot"}, ensure_ascii=False),
        encoding="utf-8",
    )

    converted = convert_directory(source, destination)

    assert converted == 3
    note = (destination / "notes.md").read_text(encoding="utf-8")
    csv_document = (destination / "data" / "cards.csv.md").read_text(encoding="utf-8")
    json_document = (destination / "data" / "metadata.json.md").read_text(encoding="utf-8")

    assert "> 資料類型：原始 Markdown" in note
    assert "內容。" in note
    assert "| name | meaning |" in csv_document
    assert "\ufeffname" not in csv_document
    assert "資料欄位：name、meaning" in csv_document
    assert "**system**：tarot" in json_document
    assert "```json" not in json_document
