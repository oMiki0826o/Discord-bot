"""
tests/test_command_safety.py

Modification():

- 驗證敏感 Slash Command 的執行期權限檢查。
- 驗證伺服器限定指令不會成為使用者安裝指令。
- 驗證 Help 分類名稱維持面向使用者的顯示文字。

本檔提供不需連線 Discord 的指令安全與介面一致性檢查。
"""

from __future__ import annotations

import ast
from pathlib import Path

from bot.core.modules.metadata import read_module_metadata


ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "bot" / "mod"


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [ast.unparse(item) for item in node.decorator_list]


def test_default_permissions_have_runtime_check() -> None:
    missing: list[str] = []
    for path in sorted(MOD.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = _decorators(node)
            has_default = any("app_commands.default_permissions" in item for item in decorators)
            has_runtime = any("app_commands.checks.has_permissions" in item for item in decorators)
            if has_default and not has_runtime:
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno} ({node.name})")
    assert not missing, "敏感指令缺少執行期權限檢查：" + ", ".join(missing)


def test_guild_only_commands_are_not_user_installed() -> None:
    missing: list[str] = []
    for path in sorted(MOD.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = _decorators(node)
            if not any(item == "app_commands.guild_only()" for item in decorators):
                continue
            if not any(item == "app_commands.allowed_installs(guilds=True, users=False)" for item in decorators):
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno} ({node.name})")
    assert not missing, "Guild-only Slash Command 缺少安裝範圍限制：" + ", ".join(missing)


def test_help_category_names_are_user_facing() -> None:
    expected = {"basic": "基本功能", "system": "系統管理", "guild": "伺服器設定", "music": "音樂播放"}
    for module_name, label in expected.items():
        metadata = read_module_metadata(MOD / module_name / "extension.py", module_name=module_name)
        assert metadata.display_name == label
