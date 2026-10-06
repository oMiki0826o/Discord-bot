"""
tests/test_ai_data_sync.py

Modification():

- 提供 test ai data sync 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import json

from bot.mod.ai.data_sync import OwnerDataService
from bot.mod.ai.data import initialize_data_dir
from bot.mod.ai.database import AiDatabase
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

    first = service.preview()
    service.mark_applied()
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
