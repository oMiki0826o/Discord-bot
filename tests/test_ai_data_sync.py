"""
tests/test_ai_data_sync.py

Modification():

- 提供 test ai data sync 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
- 驗證大型知識庫 validation 不會重複走訪來源樹。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bot.mod.ai.data_sync import OwnerDataService
from bot.mod.ai.data import initialize_data_dir
from bot.mod.ai.database import AiDatabase
from bot.mod.ai.assembly import AiModule
from bot.mod.ai.memory.manual_sync import ManualMemorySyncService
from bot.mod.ai.prompt.loader import PromptSourceLoader
from bot.mod.ai.knowledge.source import KnowledgeSourceReader


def _write_prompt(root, name: str, content: str) -> None:
    prompt = root / "prompt"
    prompt.mkdir(exist_ok=True)
    (prompt / name).write_text(content, encoding="utf-8")


def _write_prompt_resources(root) -> None:
    (root / "personas" / "default").mkdir(parents=True)
    (root / "system.txt").write_text("system", encoding="utf-8")
    (root / "personas" / "default" / "persona.txt").write_text("persona", encoding="utf-8")
    (root / "personas" / "default" / "background.txt").write_text("background", encoding="utf-8")


class _KnowledgeRecorder:
    def __init__(self) -> None:
        self.pruned: list[set[str]] = []
        self.chunk_chars = 2_000

    def remove_sources_not_in(self, source_ids: set[str]) -> None:
        self.pruned.append(set(source_ids))


class _ControlledRetrieval:
    def __init__(self, *, fail: bool = False, pause: bool = False) -> None:
        self.fail = fail
        self.pause = pause
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.embedding_model = "test-embedding"
        self.embedder = self._embed

    async def _embed(self, content: str) -> tuple[float, ...]:
        await self.index_document(content, now=0)
        return (1.0, 0.0)

    async def index_document(self, _document, *, now: int) -> None:
        del now
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            if self.fail:
                raise RuntimeError("index unavailable")
            if self.pause:
                await self.release.wait()
            else:
                await asyncio.sleep(0)
        finally:
            self.active -= 1


def _sync_module(tmp_path: Path, retrieval: _ControlledRetrieval) -> tuple[AiModule, OwnerDataService, _KnowledgeRecorder]:
    data = tmp_path / "data"
    knowledge_dir = data / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "guide.md").write_text("# Guide\nUseful text", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    manual = ManualMemorySyncService(database, data / "users_memory")
    prompts = PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt")
    owner_data = OwnerDataService(data, manual_memory=manual, prompts=prompts)
    knowledge = _KnowledgeRecorder()
    module = AiModule(
        service=None,
        attachments=None,
        worker=None,
        settings=None,
        knowledge=knowledge,
        retrieval=retrieval,
        profiles=None,
        prompts=prompts,
        knowledge_dir=knowledge_dir,
        manual_memory=manual,
        global_memory=None,
        operations=None,
        summaries=None,
        search_cache=None,
        provider=None,
        owner_data=owner_data,
        mirror=None,
    )
    return module, owner_data, knowledge


def test_initialize_data_dir_deploys_all_complete_persona_profiles_without_overwriting(tmp_path) -> None:
    resources = tmp_path / "resources"
    prompt_resources = resources / "prompt"
    _write_prompt_resources(prompt_resources)
    firefly = prompt_resources / "personas" / "firefly"
    firefly.mkdir(parents=True)
    (firefly / "persona.txt").write_text("packaged persona", encoding="utf-8")
    (firefly / "background.txt").write_text("packaged background", encoding="utf-8")
    data_dir = tmp_path / "data"
    existing = data_dir / "prompt" / "personas" / "firefly" / "persona.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("custom persona", encoding="utf-8")

    initialize_data_dir(data_dir, resource_dir=resources)

    deployed = data_dir / "prompt" / "personas" / "firefly"
    assert existing.read_text(encoding="utf-8") == "custom persona"
    assert (deployed / "background.txt").read_text(encoding="utf-8") == "packaged background"


def test_owner_data_validation_reports_invalid_prompt_and_memory_without_writing(tmp_path) -> None:
    data = tmp_path / "data"
    users = data / "users_memory"
    users.mkdir(parents=True)
    (users / "bad.json").write_text("{}", encoding="utf-8")
    _write_prompt(data, "keywords.json", "{invalid json")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    manual = ManualMemorySyncService(database, users)
    resources = data / "resources"
    _write_prompt_resources(resources)
    prompts = PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt")
    service = OwnerDataService(data, manual_memory=manual, prompts=prompts)

    report = service.validate()

    assert report.valid is False
    assert any("bad.json" in item for item in report.issues)
    assert any("keywords.json" in item for item in report.issues)
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM manual_memory_records").fetchone()[0] == 0


def test_owner_data_preview_counts_knowledge_and_manual_records(tmp_path) -> None:
    data = tmp_path / "data"
    users = data / "users_memory"
    users.mkdir(parents=True)
    (users / "Lucky(12345678901234567).json").write_text(json.dumps({
        "user_id": "12345678901234567", "memories": [{"content": "likes tea"}],
    }), encoding="utf-8")
    knowledge = data / "knowledge"
    knowledge.mkdir()
    (knowledge / "guide.md").write_text("# Guide\nUseful text", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = data / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, users),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )

    report = service.preview()

    assert report.valid is True
    assert report.manual_records == 1
    assert report.knowledge_documents == 1


def test_owner_data_snapshot_includes_every_supported_knowledge_format(tmp_path) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "guide.md").write_text("guide", encoding="utf-8")
    (knowledge / "Server.java").write_text("class Server {}", encoding="utf-8")
    (knowledge / "load.mcfunction").write_text("say loaded", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )

    validation = service.validate()
    with service.materialize_snapshot(validation) as snapshot:
        names = {
            path.relative_to(snapshot).as_posix()
            for path in snapshot.rglob("*")
            if path.is_file()
        }
        service.mark_snapshot_applied(validation, snapshot)

    assert validation.valid
    assert validation.knowledge_documents == 3
    assert names == {
        "knowledge/Server.java",
        "knowledge/guide.md",
        "knowledge/load.mcfunction",
    }
    with database.connect() as connection:
        stored = {
            row[0]
            for row in connection.execute(
                "SELECT source_path FROM ai_data_manifest WHERE source_type = 'knowledge'"
            )
        }
    assert stored == names


def test_owner_data_preview_tracks_changed_and_removed_sources(tmp_path) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    source = knowledge / "guide.md"
    source.write_text("first", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )

    first = service.validate()
    service.mark_applied(first)
    source.write_text("second", encoding="utf-8")
    second = service.preview()
    source.unlink()
    third = service.preview()

    assert first.changed_sources == 1
    assert second.changed_sources == 1
    assert third.removed_sources == 1


def test_owner_data_validation_rejects_blank_knowledge_documents(tmp_path) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "empty.md").write_text(" \n", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )

    report = service.validate()

    assert report.valid is False
    assert any("knowledge/empty.md" in issue and "blank" in issue for issue in report.issues)


def test_knowledge_source_reader_accepts_java_source_files(tmp_path) -> None:
    root = tmp_path / "knowledge"
    source = root / "minecraft" / "Server.java"
    source.parent.mkdir(parents=True)
    source.write_text("class Server {}", encoding="utf-8")

    document = KnowledgeSourceReader(root).read("minecraft/Server.java")

    assert document.title == "Server"
    assert document.content == "class Server {}"


def test_knowledge_source_reader_accepts_mcfunction_data_pack_files(tmp_path) -> None:
    root = tmp_path / "knowledge"
    source = root / "minecraft_commands" / "data" / "example" / "functions" / "load.mcfunction"
    source.parent.mkdir(parents=True)
    source.write_text("say loaded", encoding="utf-8")

    document = KnowledgeSourceReader(root).read("minecraft_commands/data/example/functions/load.mcfunction")

    assert document.title == "load"
    assert document.content == "say loaded"


def test_owner_data_validation_scans_the_knowledge_tree_once(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "guide.md").write_text("# Guide\nUseful text", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )
    original_rglob = Path.rglob
    scans = 0

    def counted_rglob(path: Path, pattern: str):
        nonlocal scans
        if path in {data, knowledge}:
            scans += 1
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", counted_rglob)

    report = service.validate()

    assert report.valid
    assert report.knowledge_documents == 1
    assert scans == 1


def test_owner_data_preview_cannot_supply_manifest_for_later_apply(tmp_path) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    source = knowledge / "guide.md"
    source.write_text("version A", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )

    preview = service.preview()
    source.write_text("version B", encoding="utf-8")

    with pytest.raises(RuntimeError, match="validated snapshot"):
        service.mark_applied(preview)


def test_owner_data_apply_rejects_source_changed_after_validation(tmp_path) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    source = knowledge / "guide.md"
    source.write_text("version A", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )

    validation = service.validate()
    source.write_text("version B", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after validation"):
        service.mark_applied(validation)


def test_owner_data_snapshot_stays_consistent_when_live_source_changes(tmp_path) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    source = knowledge / "guide.md"
    source.write_text("version A", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )
    validation = service.validate()

    with service.materialize_snapshot(validation) as snapshot:
        source.write_text("version B", encoding="utf-8")
        assert (snapshot / "knowledge" / "guide.md").read_text(encoding="utf-8") == "version A"
        service.mark_snapshot_applied(validation, snapshot)

    report = service.preview()
    assert report.changed_sources == 1
    with database.connect() as connection:
        stored = connection.execute(
            "SELECT content_hash FROM ai_data_manifest WHERE source_path = 'knowledge/guide.md'"
        ).fetchone()[0]
    assert stored == __import__("hashlib").sha256(b"version A").hexdigest()


def test_owner_data_sync_state_is_persistent(tmp_path) -> None:
    data = tmp_path / "data"
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )

    service.set_sync_state("failed", "disk unavailable")

    assert service.sync_state()["status"] == "failed"
    assert service.sync_state()["detail"] == "disk unavailable"
    assert service.sync_state()["operation_id"] == ""

    service.set_sync_state("cancelled", "cancelled", operation_id="operation-1")
    assert service.sync_state()["status"] == "cancelled"
    assert service.sync_state()["operation_id"] == "operation-1"


def test_owner_data_validation_reads_only_sources_with_changed_metadata(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    knowledge = data / "knowledge"
    knowledge.mkdir(parents=True)
    source = knowledge / "guide.md"
    source.write_text("stable", encoding="utf-8")
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    resources = tmp_path / "resources"
    _write_prompt_resources(resources)
    service = OwnerDataService(
        data,
        manual_memory=ManualMemorySyncService(database, data / "users_memory"),
        prompts=PromptSourceLoader(resource_dir=resources, override_dir=data / "prompt"),
    )
    first = service.validate()
    service.mark_applied(first)
    original = Path.read_bytes
    reads = 0

    def counted(path: Path) -> bytes:
        nonlocal reads
        if path == source:
            reads += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    unchanged = service.preview()
    source.touch()
    changed = service.preview()

    assert unchanged.changed_sources == 0
    assert changed.changed_sources == 0
    assert reads == 1


def test_ai_owner_data_sync_serializes_concurrent_requests(tmp_path) -> None:
    async def scenario() -> None:
        retrieval = _ControlledRetrieval(pause=True)
        module, owner_data, _knowledge = _sync_module(tmp_path, retrieval)

        first = asyncio.create_task(module.sync_owner_data())
        await retrieval.started.wait()
        second = asyncio.create_task(module.sync_owner_data())
        await asyncio.sleep(0)
        assert retrieval.max_active == 1

        retrieval.release.set()
        assert await first == (0, 1)
        assert await second == (0, 0)
        assert retrieval.max_active == 1
        assert owner_data.sync_state()["status"] == "completed"

    asyncio.run(scenario())


def test_ai_owner_data_sync_cancellation_is_recorded_and_does_not_prune(tmp_path) -> None:
    async def scenario() -> None:
        retrieval = _ControlledRetrieval(pause=True)
        module, owner_data, knowledge = _sync_module(tmp_path, retrieval)

        task = asyncio.create_task(module.sync_owner_data())
        await retrieval.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        state = owner_data.sync_state()
        assert state["status"] == "cancelled"
        assert state["operation_id"]
        assert knowledge.pruned == []

    asyncio.run(scenario())


def test_ai_owner_data_sync_index_failure_preserves_existing_sources(tmp_path) -> None:
    async def scenario() -> None:
        retrieval = _ControlledRetrieval(fail=True)
        module, owner_data, knowledge = _sync_module(tmp_path, retrieval)

        with pytest.raises(RuntimeError, match="index unavailable"):
            await module.sync_owner_data()

        assert knowledge.pruned == []
        assert owner_data.sync_state()["status"] == "failed"

    asyncio.run(scenario())
