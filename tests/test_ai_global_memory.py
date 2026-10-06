"""
tests/test_ai_global_memory.py

Modification():

- 提供 test ai global memory 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import json

from bot.mod.ai.memory.global_memory import GlobalMemoryService
from bot.mod.ai.prompt.loader import PromptSourceLoader


def _loader(tmp_path):
    resources = tmp_path / "resources"
    (resources / "personas" / "default").mkdir(parents=True)
    (resources / "system.txt").write_text("system", encoding="utf-8")
    (resources / "personas" / "default" / "persona.txt").write_text("persona", encoding="utf-8")
    (resources / "personas" / "default" / "background.txt").write_text("background", encoding="utf-8")
    overrides = tmp_path / "data" / "prompt"
    overrides.mkdir(parents=True)
    return PromptSourceLoader(resource_dir=resources, override_dir=overrides)


def test_global_memory_upsert_reload_and_remove_uses_json_source_of_truth(tmp_path) -> None:
    loader = _loader(tmp_path)
    service = GlobalMemoryService(loader.override_dir / "memory.json", prompts=loader)

    service.upsert("project.status", "Release bot is the active project.", importance=4)

    assert loader.load().global_memory == ("Release bot is the active project.",)
    assert service.list() == ({"key": "project.status", "content": "Release bot is the active project.", "importance": 4},)
    assert service.remove("project.status") is True
    assert loader.load().global_memory == ()
    assert json.loads((loader.override_dir / "memory.json").read_text(encoding="utf-8"))["memories"] == []
