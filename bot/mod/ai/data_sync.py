"""
bot/mod/ai/data_sync.py

Modification():

- 提供 Owner 可編輯 AI 資料來源的安全驗證。
- 僅處理 `.json`、`.md`、`.txt` 文字資料，忽略其他非支援檔案。
- Knowledge 文件僅支援 `.md` 與 `.txt`。
- 維持來源檔案唯讀驗證，不主動修改來源或 SQLite。
- 將 validation、文件統計與 manifest 合併為一次來源走訪，避免大型知識庫拖慢模組啟動。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PromptSourceError
from .memory.manual_sync import ManualMemorySyncService
from .prompt.loader import PromptSourceLoader


# ── 支援格式 ──

SUPPORTED_TEXT_SUFFIXES = frozenset({
    ".json",
    ".md",
    ".txt",
})

KNOWLEDGE_SUFFIXES = frozenset({
    ".md",
    ".txt",
})


# ── 驗證報告 ──

@dataclass(frozen=True, slots=True)
class OwnerDataReport:
    """Owner 可編輯 AI 資料的驗證結果。"""

    valid: bool
    manual_records: int
    knowledge_documents: int
    changed_sources: int = 0
    removed_sources: int = 0
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    """一次走訪取得 Owner data validation 所需的唯讀資訊。"""

    issues: tuple[str, ...]
    knowledge_documents: int
    manifest: dict[str, tuple[str, str]]


# ── Owner 資料服務 ──

class OwnerDataService:
    """驗證 Owner 可編輯資料，不修改來源檔案或 SQLite。"""

    def __init__(
        self,
        root: Path,
        *,
        manual_memory: ManualMemorySyncService,
        prompts: PromptSourceLoader,
        max_source_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        if max_source_bytes < 1:
            raise ValueError("max_source_bytes must be positive")

        self.root = Path(root)
        self.manual_memory = manual_memory
        self.prompts = prompts
        self.max_source_bytes = max_source_bytes
        self._validated_manifest: dict[str, tuple[str, str]] | None = None

    # ── 公開介面 ──

    def validate(self) -> OwnerDataReport:
        """驗證目前所有受支援的 Owner 可編輯資料來源。"""

        snapshot = self._source_snapshot()
        issues = list(snapshot.issues)

        records = 0
        try:
            records = self.manual_memory.validate().records
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(f"users_memory: {exc}")

        issues.extend(self._validate_prompt_json())

        try:
            self.prompts.load()
        except (ValueError, PromptSourceError) as exc:
            issues.append(f"prompt: {exc}")

        changed, removed = self._manifest_diff(snapshot.manifest)

        valid = not issues
        self._validated_manifest = dict(snapshot.manifest) if valid else None
        return OwnerDataReport(
            valid=valid,
            manual_records=records,
            knowledge_documents=snapshot.knowledge_documents,
            changed_sources=changed,
            removed_sources=removed,
            issues=tuple(issues),
        )

    def preview(self) -> OwnerDataReport:
        """以與正式驗證相同的唯讀契約預覽資料狀態。"""

        return self.validate()

    def mark_applied(self) -> None:
        """僅在同步成功後記錄目前已驗證的來源快照。"""

        sources = self._validated_manifest
        self._validated_manifest = None
        if sources is None:
            sources = self._source_manifest()

        with self.manual_memory.database.transaction() as connection:
            connection.execute("DELETE FROM ai_data_manifest")

            connection.executemany(
                """
                INSERT INTO ai_data_manifest (
                    source_path,
                    content_hash,
                    source_type,
                    applied_at
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        path,
                        content_hash,
                        source_type,
                        int(time.time()),
                    )
                    for path, (content_hash, source_type) in sources.items()
                ],
            )

    # ── 來源掃描 ──

    def _scan_sources(self) -> list[str]:
        """掃描並驗證所有受支援的文字來源。"""

        return list(self._source_snapshot().issues)

    def _source_snapshot(self) -> _SourceSnapshot:
        """避免 validate 在大型知識庫上重複走訪與讀取相同來源。"""

        issues: list[str] = []
        knowledge_documents = 0
        manifest: dict[str, tuple[str, str]] = {}

        if not self.root.exists():
            return _SourceSnapshot(
                issues=(f"data root does not exist: {self.root}",),
                knowledge_documents=0,
                manifest=manifest,
            )

        root = self.root.resolve()

        for path in sorted(self.root.rglob("*")):
            if path.is_dir():
                continue

            relative = path.relative_to(self.root).as_posix()
            if (
                relative.startswith("knowledge/")
                and path.is_file()
                and not path.is_symlink()
                and path.suffix.casefold() in KNOWLEDGE_SUFFIXES
                and path.name != "填寫說明.md"
            ):
                knowledge_documents += 1

            # 不支援的副檔名不屬於 AI 可編輯資料來源。
            if not self._is_supported_text_source(path):
                continue

            if path.is_symlink():
                issues.append(
                    f"{relative}: symbolic links are not allowed"
                )
                continue

            try:
                path.resolve(strict=True).relative_to(root)
                size = path.stat().st_size
            except (OSError, ValueError) as exc:
                issues.append(
                    f"{relative}: cannot read source ({exc})"
                )
                continue

            if size > self.max_source_bytes:
                issues.append(
                    f"{relative}: exceeds {self.max_source_bytes} bytes"
                )
                continue

            try:
                raw = path.read_bytes()
            except OSError as exc:
                issues.append(
                    f"{relative}: cannot read source ({exc})"
                )
                continue

            source_type = self._source_type(relative)
            if source_type is not None:
                manifest[relative] = (
                    hashlib.sha256(raw).hexdigest(),
                    source_type,
                )

            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                issues.append(
                    f"{relative}: must be UTF-8"
                )
                continue

            if (
                relative.startswith("knowledge/")
                and path.suffix.casefold() in KNOWLEDGE_SUFFIXES
                and path.name != "填寫說明.md"
                and not text.strip()
            ):
                issues.append(
                    f"{relative}: knowledge document must not be blank"
                )

        return _SourceSnapshot(
            issues=tuple(issues),
            knowledge_documents=knowledge_documents,
            manifest=manifest,
        )

    # ── Prompt JSON 驗證 ──

    def _validate_prompt_json(self) -> list[str]:
        """驗證系統管理的 Prompt JSON 資料格式。"""

        issues: list[str] = []

        for name in (
            "keywords.json",
            "blocked_words.json",
            "memory.json",
        ):
            path = self.root / "prompt" / name

            if not path.is_file():
                continue

            try:
                value: Any = json.loads(
                    path.read_text(encoding="utf-8")
                )

                if not isinstance(value, (list, dict)):
                    raise ValueError(
                        "must be a JSON array or object"
                    )

                self.prompts._read_json_strings(name)

            except (
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                issues.append(
                    f"prompt/{name}: {exc}"
                )

        return issues

    # ── Knowledge 統計 ──

    def _knowledge_documents(self) -> int:
        """計算目前有效的 Knowledge Markdown 與文字文件數量。"""

        root = self.root / "knowledge"

        if not root.is_dir():
            return 0

        return sum(
            1
            for path in root.rglob("*")
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix.casefold() in KNOWLEDGE_SUFFIXES
                and path.name != "填寫說明.md"
            )
        )

    # ── 來源 Manifest ──

    def _source_manifest(self) -> dict[str, tuple[str, str]]:
        """建立目前受支援資料來源的內容雜湊快照。"""

        result: dict[str, tuple[str, str]] = {}

        if not self.root.is_dir():
            return result

        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue

            if not self._is_supported_text_source(path):
                continue

            relative = path.relative_to(self.root).as_posix()

            if relative.startswith("users_memory/"):
                source_type = "user_memory"
            elif relative.startswith("knowledge/"):
                source_type = "knowledge"
            elif relative.startswith("prompt/"):
                source_type = "prompt"
            else:
                continue

            try:
                raw = path.read_bytes()
            except OSError:
                continue

            if len(raw) > self.max_source_bytes:
                continue

            result[relative] = (
                hashlib.sha256(raw).hexdigest(),
                source_type,
            )

        return result

    def _manifest_diff(
        self,
        current: dict[str, tuple[str, str]] | None = None,
    ) -> tuple[int, int]:
        """比較目前來源與上一次已套用來源的差異。"""

        if current is None:
            current = self._source_manifest()

        with self.manual_memory.database.connect() as connection:
            previous = {
                str(row["source_path"]): (
                    str(row["content_hash"]),
                    str(row["source_type"]),
                )
                for row in connection.execute(
                    """
                    SELECT
                        source_path,
                        content_hash,
                        source_type
                    FROM ai_data_manifest
                    """
                )
            }

        changed = sum(
            1
            for path, value in current.items()
            if previous.get(path) != value
        )

        removed = sum(
            1
            for path in previous
            if path not in current
        )

        return changed, removed

    # ── 共用工具 ──

    @staticmethod
    def _is_supported_text_source(path: Path) -> bool:
        """判斷檔案是否屬於允許讀取的文字資料格式。"""

        return path.suffix.casefold() in SUPPORTED_TEXT_SUFFIXES

    @staticmethod
    def _source_type(relative: str) -> str | None:
        if relative.startswith("users_memory/"):
            return "user_memory"
        if relative.startswith("knowledge/"):
            return "knowledge"
        if relative.startswith("prompt/"):
            return "prompt"
        return None
