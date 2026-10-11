"""
tests/test_architecture_boundaries.py

Modification():

- 驗證 Core 不反向依賴功能模組。
- 驗證模組直接跨模組 import 必須由 extension manifest 宣告。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOT_ROOT = PROJECT_ROOT / "bot"
MODULE_ROOT = BOT_ROOT / "mod"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)


def _import_targets(path: Path) -> set[str]:
    package = _module_name(path).split(".")[:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    continue
                prefix = package[: len(package) - (node.level - 1)]
                target = ".".join((*prefix, *(node.module or "").split("."))).rstrip(".")
            else:
                target = node.module or ""
            if target:
                targets.add(target)
    return targets


def _module_dependencies() -> dict[str, frozenset[str]]:
    dependencies: dict[str, frozenset[str]] = {}
    for extension in sorted(MODULE_ROOT.glob("*/extension.py")):
        module = extension.parent.name
        tree = ast.parse(extension.read_text(encoding="utf-8"), filename=str(extension))
        declared: tuple[str, ...] | None = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = (node.target,)
                value = node.value
            else:
                continue
            if value is not None and any(
                isinstance(target, ast.Name) and target.id == "MODULE_DEPENDENCIES"
                for target in targets
            ):
                declared = ast.literal_eval(value)
                break
        assert declared is not None, f"{extension} must declare MODULE_DEPENDENCIES"
        dependencies[module] = frozenset(declared)
    return dependencies


def _module_from_target(target: str) -> str | None:
    parts = target.split(".")
    if len(parts) >= 3 and parts[:2] == ["bot", "mod"]:
        return parts[2]
    return None


def test_core_does_not_import_feature_modules() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT)} -> {target}"
        for path in sorted((BOT_ROOT / "core").rglob("*.py"))
        for target in _import_targets(path)
        if _module_from_target(target) is not None
    ]

    assert violations == []


def test_direct_module_imports_are_declared_by_the_manifest() -> None:
    dependencies = _module_dependencies()
    violations: list[str] = []
    for path in sorted(MODULE_ROOT.rglob("*.py")):
        source = path.relative_to(MODULE_ROOT).parts[0]
        for target in _import_targets(path):
            target_module = _module_from_target(target)
            if target_module is None or target_module == source:
                continue
            if target_module not in dependencies[source]:
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT)} imports {target} "
                    f"without declaring {target_module}"
                )

    assert violations == []
