"""
tests/test_release_static.py

Modification():

- 驗證發布版 Python 語法與檔頭規範。
- 驗證 Settings JSON 格式。
- 驗證 Module metadata 與依賴圖。
- 防止 silent pass 與不應提交的發布內容。

本檔提供不需 Discord 連線即可執行的發布前靜態測試。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"


def _python_files() -> list[Path]:
    return [
        ROOT / "main.py",
        *BOT.rglob("*.py"),
        *(ROOT / "tools").rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
    ]


def test_python_files_parse() -> None:
    for path in _python_files():
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_python_headers() -> None:
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if path.name == "__init__.py" and not text.strip():
            continue
        tree = ast.parse(text, filename=str(path))
        header = ast.get_docstring(tree, clean=False)
        assert header, f"缺少檔頭 docstring：{path}"
        relative = path.relative_to(ROOT).as_posix()
        assert relative in header.splitlines()[:3], f"檔頭缺少檔名：{path}"
        assert "Modification():" in header, f"檔頭缺少 Modification：{path}"


def test_no_silent_pass() -> None:
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Pass), f"禁止 silent pass：{path}:{node.lineno}"


def test_gitignore_excludes_python_cache() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in gitignore
    assert "*.py[cod]" in gitignore


def test_settings_are_json_objects() -> None:
    for path in (ROOT / "settings").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"Settings 根節點不是 Object：{path}"


def test_module_dependency_graph() -> None:
    modules: dict[str, tuple[str, ...]] = {}
    for extension in (BOT / "mod").glob("*/extension.py"):
        tree = ast.parse(extension.read_text(encoding="utf-8"), filename=str(extension))
        dependencies: tuple[str, ...] = ()
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(target, ast.Name) and target.id == "MODULE_DEPENDENCIES" for target in node.targets):
                value = ast.literal_eval(node.value)
                assert isinstance(value, (tuple, list))
                assert all(isinstance(item, str) and item for item in value)
                dependencies = tuple(value)
        modules[extension.parent.name] = dependencies

    for name, dependencies in modules.items():
        assert name not in dependencies, f"Module 不可依賴自己：{name}"
        missing = set(dependencies) - modules.keys()
        assert not missing, f"Module {name} 缺少依賴：{sorted(missing)}"

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        assert name not in visiting, f"偵測到循環依賴：{name}"
        visiting.add(name)
        for dependency in modules[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in modules:
        visit(name)


def test_release_documentation_uses_real_entrypoint() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python main.py" in readme
    assert "python bot.py" not in readme


def test_env_example_contains_no_placeholder_secrets() -> None:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    assert values.get("DISCORD_TOKEN") == ""
    assert values.get("OWNER_ID") == ""
    assert values.get("GEMINI_API") == ""


def test_source_headers_do_not_contain_legacy_test_mod_paths() -> None:
    invalid: list[str] = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        header = ast.get_docstring(tree, clean=False)
        if header is not None and "test_mod/" in header:
            invalid.append(str(path.relative_to(ROOT)))
    assert not invalid, "檔頭仍含舊 test_mod 路徑：" + ", ".join(invalid)
