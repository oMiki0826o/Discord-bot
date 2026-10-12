"""
bot/mod/ai/data_sync.py

Modification():

- 提供 Owner 可編輯 AI 資料來源的安全驗證。
- Knowledge 格式與 KnowledgeSourceReader 共用單一副檔名契約。
- 維持來源檔案唯讀驗證，不主動修改來源或 SQLite。
- 將 validation、文件統計與 manifest 合併為一次來源走訪，避免大型知識庫拖慢模組啟動。
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .errors import PromptSourceError
from .knowledge.source import KNOWLEDGE_SOURCE_SUFFIXES
from .memory.manual_sync import ManualMemorySyncService
from .prompt.loader import PromptSourceLoader


# ── 支援格式 ──

SUPPORTED_TEXT_SUFFIXES = frozenset({
    ".json",
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
    _manifest: tuple[tuple[str, str, str], ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _can_apply: bool = field(default=False, repr=False, compare=False)


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
    # ── 公開介面 ──

    def validate(self) -> OwnerDataReport:
        """驗證目前所有受支援的 Owner 可編輯資料來源。"""

        return self._inspect(can_apply=True)

    def preview(self) -> OwnerDataReport:
        """唯讀預覽資料狀態，不產生可供套用的驗證憑證。"""

        return self._inspect(can_apply=False)

    def _inspect(self, *, can_apply: bool) -> OwnerDataReport:
        """建立一次性來源快照；是否可套用由呼叫用途明確決定。"""

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
        return OwnerDataReport(
            valid=valid,
            manual_records=records,
            knowledge_documents=snapshot.knowledge_documents,
            changed_sources=changed,
            removed_sources=removed,
            issues=tuple(issues),
            _manifest=tuple(
                (path, content_hash, source_type)
                for path, (content_hash, source_type) in sorted(snapshot.manifest.items())
            ),
            _can_apply=can_apply and valid,
        )

    def mark_applied(self, validation: OwnerDataReport) -> None:
        """同步成功後記錄同一份且仍未變動的驗證快照。"""

        self._mark_applied(validation, source_root=None)

    def _mark_applied(
        self,
        validation: OwnerDataReport,
        *,
        source_root: Path | None,
    ) -> None:
        sources = self._validation_sources(validation)
        current = self._source_manifest(source_root)
        if current != sources:
            if source_root is None:
                raise RuntimeError("AI data sources changed after validation; retry synchronization")
            raise RuntimeError("materialized AI data snapshot does not match validation")

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

    def mark_snapshot_applied(
        self,
        validation: OwnerDataReport,
        source_root: Path,
    ) -> None:
        """記錄已由同一 immutable snapshot 完成的同步結果。"""

        self._mark_applied(validation, source_root=source_root)

    def set_sync_state(self, status: str, detail: str = "", *, operation_id: str = "") -> None:
        if status not in {"idle", "staging", "applying", "completed", "failed", "cancelled"}:
            raise ValueError("invalid AI data sync status")
        with self.manual_memory.database.transaction() as connection:
            connection.execute(
                "UPDATE ai_data_sync_state SET status = ?, detail = ?, operation_id = ?, updated_at = ? "
                "WHERE singleton = 1",
                (status, detail[:500], operation_id[:64], int(time.time())),
            )

    def sync_state(self) -> dict[str, str | int]:
        with self.manual_memory.database.connect() as connection:
            row = connection.execute(
                "SELECT status, detail, operation_id, updated_at FROM ai_data_sync_state WHERE singleton = 1"
            ).fetchone()
        return {
            "status": str(row["status"]),
            "detail": str(row["detail"]),
            "operation_id": str(row["operation_id"]),
            "updated_at": int(row["updated_at"]),
        }

    @contextmanager
    def materialize_snapshot(self, validation: OwnerDataReport):
        """Copy validated bytes to an immutable per-sync source directory."""

        sources = self._validation_sources(validation)
        with TemporaryDirectory(prefix="discord-bot-ai-sync-") as directory:
            snapshot = Path(directory)
            for relative, (expected_hash, _source_type) in sources.items():
                source = self.root / relative
                if source.is_symlink() or not source.is_file():
                    raise RuntimeError("AI data sources changed after validation; retry synchronization")
                raw = source.read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected_hash:
                    raise RuntimeError("AI data sources changed after validation; retry synchronization")
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            yield snapshot

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
                and path.suffix.casefold() in KNOWLEDGE_SOURCE_SUFFIXES
                and path.name != "填寫說明.md"
            ):
                knowledge_documents += 1

            # 不支援的副檔名不屬於 AI 可編輯資料來源。
            if not self._is_supported_text_source(path, relative):
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
                and path.suffix.casefold() in KNOWLEDGE_SOURCE_SUFFIXES
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
                and path.suffix.casefold() in KNOWLEDGE_SOURCE_SUFFIXES
                and path.name != "填寫說明.md"
            )
        )

    # ── 來源 Manifest ──

    def _source_manifest(
        self,
        source_root: Path | None = None,
    ) -> dict[str, tuple[str, str]]:
        """建立目前受支援資料來源的內容雜湊快照。"""

        result: dict[str, tuple[str, str]] = {}
        root = self.root if source_root is None else Path(source_root)

        if not root.is_dir():
            return result

        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue

            relative = path.relative_to(root).as_posix()
            if not self._is_supported_text_source(path, relative):
                continue

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

    @staticmethod
    def _validation_sources(
        validation: OwnerDataReport,
    ) -> dict[str, tuple[str, str]]:
        if not validation.valid or not validation._can_apply:
            raise RuntimeError("mark_applied requires a valid validated snapshot")
        return {
            path: (content_hash, source_type)
            for path, content_hash, source_type in validation._manifest
        }

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
    def _is_supported_text_source(path: Path, relative: str) -> bool:
        """判斷檔案是否屬於允許讀取的文字資料格式。"""

        suffix = path.suffix.casefold()
        if relative.startswith("knowledge/"):
            return suffix in KNOWLEDGE_SOURCE_SUFFIXES
        return suffix in SUPPORTED_TEXT_SUFFIXES

    @staticmethod
    def _source_type(relative: str) -> str | None:
        if relative.startswith("users_memory/"):
            return "user_memory"
        if relative.startswith("knowledge/"):
            return "knowledge"
        if relative.startswith("prompt/"):
            return "prompt"
        return None
