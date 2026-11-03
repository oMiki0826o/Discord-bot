"""
bot/mod/agent/assembly.py

Modification():

- 組裝只依賴 AI public facade 的 Agent Runtime factory。
- 將 Skills 與 read-only Tool Registry 保持在 Agent Module 邊界內。
"""

from __future__ import annotations

from pathlib import Path

from .tools.builtin import build_readonly_registry
from .config import AgentSettings
from .provider_adapter import AiModelAdapter
from .runtime import AgentRuntime
from .skills import SkillService
from .skills.bootstrap import DEFAULT_SKILL_ROOT


def build_runtime_factory(
    settings: AgentSettings,
    *,
    skills_dir: Path | None = None,
):
    """建立可由 AI RuntimeHost 在首次載入或 reload 時重建的 factory。"""

    root = Path(skills_dir) if skills_dir is not None else DEFAULT_SKILL_ROOT

    def create(services) -> AgentRuntime:
        skills = SkillService(root)
        return AgentRuntime(
            AiModelAdapter(services),
            build_readonly_registry(services, skills=skills),
            settings,
        )

    return create
