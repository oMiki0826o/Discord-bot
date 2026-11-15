"""
tools/import_divination.py

Modification():

- 將外部占卜知識庫的 Markdown、CSV 與 JSON 正規化為 Markdown。
- 保留來源樹結構，供本機 AI Knowledge 索引使用。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


_SUPPORTED_SUFFIXES = frozenset({".md", ".csv", ".json"})
_SAFETY_NOTICE = "文化、歷史與研究資料；不作為科學預測、醫療、法律或財務判斷依據。"


# ── Markdown 轉換 ──────────────────────

def _metadata(*, collection: str, relative: Path, source_type: str) -> str:
    """建立每份文件共用的、可被全文檢索的來源描述。"""

    return "\n".join((
        f"> 資料庫：{collection}",
        f"> 資料類型：{source_type}",
        f"> 原始路徑：`{relative.as_posix()}`",
        f"> 使用界線：{_SAFETY_NOTICE}",
    ))


def _with_metadata(content: str, *, collection: str, relative: Path, source_type: str) -> str:
    """保留既有 Markdown 主標題，並在其後加上可檢索來源資訊。"""

    metadata = _metadata(collection=collection, relative=relative, source_type=source_type)
    lines = content.lstrip("\ufeff").splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join((lines[0], "", metadata, "", *lines[1:])).rstrip() + "\n"
    return "\n".join((f"# {relative.stem}", "", metadata, "", content.rstrip())) + "\n"


def _markdown_table(path: Path, *, collection: str, relative: Path) -> str:
    """將 UTF-8 CSV 轉換為可檢索的 Markdown 表格。"""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return "\n".join((
            f"# {path.stem}",
            "",
            _metadata(collection=collection, relative=relative, source_type="CSV 資料表"),
            "",
            "_來源 CSV 為空。_",
            "",
        ))

    def escape(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")

    header = [escape(value) for value in rows[0]]
    body = [
        [escape(value) for value in row] + [""] * max(0, len(header) - len(row))
        for row in rows[1:]
    ]
    lines = [
        f"# {path.stem}",
        "",
        _metadata(collection=collection, relative=relative, source_type="CSV 資料表"),
        "",
        "資料欄位：" + "、".join(header),
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _item in header) + " |",
    ]
    lines.extend("| " + " | ".join(row[: len(header)]) + " |" for row in body)
    return "\n".join(lines) + "\n"


def _format_scalar(value: object) -> str:
    """以穩定、可讀的形式表示 JSON 純量。"""

    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _json_table(rows: list[dict[str, Any]]) -> list[str] | None:
    """僅在欄位一致且值為純量時，將 JSON 物件列表渲染為表格。"""

    if not rows:
        return None
    headers = list(rows[0])
    if not headers or any(list(row) != headers for row in rows):
        return None
    if any(isinstance(value, (dict, list)) for row in rows for value in row.values()):
        return None
    escaped_headers = [header.replace("|", "\\|") for header in headers]
    lines = [
        "| " + " | ".join(escaped_headers) + " |",
        "| " + " | ".join("---" for _item in escaped_headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(
            _format_scalar(row[header]).replace("|", "\\|").replace("\n", "<br>")
            for header in headers
        ) + " |")
    return lines


def _render_json(value: object, *, level: int = 2) -> list[str]:
    """將 JSON 結構展開為標題、條列與表格，提升 FTS 檢索品質。"""

    if isinstance(value, dict):
        lines: list[str] = []
        scalar_items = [item for item in value.items() if not isinstance(item[1], (dict, list))]
        for key, item in scalar_items:
            lines.append(f"- **{key}**：{_format_scalar(item)}")
        if scalar_items:
            lines.append("")
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.extend(("#" * min(level, 6) + f" {key}", ""))
                lines.extend(_render_json(item, level=level + 1))
        return lines
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return [f"- {_format_scalar(item)}" for item in value] + [""]
        if all(isinstance(item, dict) for item in value):
            table = _json_table(value)
            if table is not None:
                return table + [""]
        lines = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, (dict, list)):
                lines.extend(("#" * min(level, 6) + f" 項目 {index}", ""))
                lines.extend(_render_json(item, level=level + 1))
            else:
                lines.append(f"- {_format_scalar(item)}")
        return lines + [""]
    return [f"- {_format_scalar(value)}", ""]


def _markdown_json(path: Path, *, collection: str, relative: Path) -> str:
    """將 JSON 轉成語意化 Markdown，而不是置入難檢索的程式碼區塊。"""

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    lines = [
        f"# {path.stem}",
        "",
        _metadata(collection=collection, relative=relative, source_type="JSON 結構化資料"),
        "",
        *_render_json(value),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _target_path(relative: Path) -> Path:
    """保留副檔名來源資訊，避免 CSV 與 JSON 同名時互相覆寫。"""

    if relative.suffix.casefold() == ".md":
        return relative
    return relative.with_suffix(relative.suffix + ".md")


def _collection_name(source: Path) -> str:
    """從匯入來源名稱取得穩定的資料庫標籤。"""

    name = source.name
    if "中式" in name:
        return "中式命理與占卜"
    if "西方" in name:
        return "西方占卜"
    return name.removesuffix("知識庫").replace("_", " ")


def _atomic_write(path: Path, content: str) -> None:
    """避免轉換中斷時留下部分寫入的 Markdown。"""

    with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


# ── 匯入 ──────────────────────

def convert_directory(source: Path, destination: Path) -> int:
    """將 source 的可讀知識資料轉換至 destination，回傳文件數。"""

    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        raise ValueError(f"source directory does not exist: {source}")

    collection = _collection_name(source)
    converted = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.casefold() not in _SUPPORTED_SUFFIXES:
            continue

        relative = path.relative_to(source)
        target = destination / _target_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        suffix = path.suffix.casefold()
        if suffix == ".md":
            content = _with_metadata(
                path.read_text(encoding="utf-8-sig"),
                collection=collection,
                relative=relative,
                source_type="原始 Markdown",
            )
        elif suffix == ".csv":
            content = _markdown_table(path, collection=collection, relative=relative)
        else:
            content = _markdown_json(path, collection=collection, relative=relative)
        _atomic_write(target, content)
        converted += 1
    return converted


# ── CLI ──────────────────────

def main() -> int:
    """執行一次性占卜知識庫轉換。"""

    parser = argparse.ArgumentParser(description="Convert divination knowledge to Markdown.")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    count = convert_directory(arguments.source, arguments.destination)
    print(f"Converted {count} knowledge documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
