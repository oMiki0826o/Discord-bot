"""
tests/test_ai_owner_commands.py

Modification():

- The AI Owner command surface is a single nested `$ai` tree.
- 維護 test ai owner commands 的發布版行為與驗證契約。
"""

from __future__ import annotations

from pathlib import Path

from bot.mod.ai.commands import discord as discord_commands
from bot.mod.ai.prompt.loader import PromptSourceLoader


SOURCE = (Path(__file__).resolve().parents[1] / "bot/mod/ai/commands/discord.py").read_text(encoding="utf-8")


def test_ai_owner_operations_are_nested_and_owner_only() -> None:
    for name in ("access", "stats", "diagnose", "memory"):
        assert f'@ai_owner.group(name="{name}"' in SOURCE
    assert "@commands.is_owner()\n        async def ai_access" in SOURCE
    assert "@commands.is_owner()\n        async def ai_stats" in SOURCE
    assert "@commands.is_owner()\n        async def ai_diagnose" in SOURCE
    assert "@commands.is_owner()\n        async def ai_memory" in SOURCE


def test_ai_owner_help_lists_operation_groups() -> None:
    assert "access, stats, diagnose, memory" in SOURCE


def test_ai_owner_exposes_model_quota_cache_and_prompt_status() -> None:
    for name in ("quota", "cache", "prompt"):
        assert f'@ai_owner.command(name="{name}")' in SOURCE


def test_prompt_status_uses_the_loader_active_persona_instead_of_prompt_sources(tmp_path) -> None:
    resources = tmp_path / "resources"
    overrides = tmp_path / "prompt"
    (resources / "personas" / "default").mkdir(parents=True)
    (resources / "system.txt").write_text("system", encoding="utf-8")
    (resources / "personas" / "default" / "persona.txt").write_text("persona", encoding="utf-8")
    (resources / "personas" / "default" / "background.txt").write_text("background", encoding="utf-8")
    (overrides / "personas").mkdir(parents=True)
    (overrides / "personas" / "active.txt").write_text("default\n", encoding="utf-8")
    loader = PromptSourceLoader(resource_dir=resources, override_dir=overrides)

    status = discord_commands.prompt_status_summary(loader)

    assert status == "Prompt sources: persona=default keywords=0 blocked_words=0 global_memory=0"
